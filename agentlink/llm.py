"""Model API clients for the chat agent: OpenAI-compatible chat completions and Anthropic messages.

The agent keeps its history in a neutral form; these functions translate it per request:
  {"role": "user", "text": ...}
  {"role": "assistant", "text": ..., "tool_calls": [{"id", "name", "arguments"}], "reasoning": ...}
  {"role": "tool", "id": ..., "name": ..., "is_error": bool, "content": [text/image blocks from ToolResult]}
"""
import asyncio
import json
from dataclasses import dataclass, field

import aiohttp

NO_VISION_NOTE = "[image omitted: this model cannot view images]"


class LLMError(Exception):
    pass


@dataclass
class Reply:
    text: str
    tool_calls: list = field(default_factory=list)
    reasoning: str | None = None


def openai_messages(system, history, vision):
    messages = [{"role": "system", "content": system}]
    pending_images = []
    for message in history:
        if message["role"] != "tool" and pending_images:
            messages.append({"role": "user", "content": [{"type": "text", "text": "Images returned by the tools above."}] + pending_images})
            pending_images = []
        if message["role"] == "user":
            images = message.get("images") if vision else None
            if images:
                messages.append({"role": "user", "content": [{"type": "text", "text": message["text"]}] + [
                    {"type": "image_url", "image_url": {"url": f"data:{i['mime']};base64,{i['data']}"}} for i in images]})
            else:
                messages.append({"role": "user", "content": message["text"]})
        elif message["role"] == "assistant":
            entry = {"role": "assistant", "content": message["text"] or None}
            if message.get("tool_calls"):
                entry["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                    "name": c["name"], "arguments": json.dumps(c["arguments"] if c["arguments"] is not None else {}, ensure_ascii=False)}}
                    for c in message["tool_calls"]]
            if message.get("reasoning"):
                entry["reasoning_content"] = message["reasoning"]
            messages.append(entry)
        else:
            parts = []
            for block in message["content"]:
                if block["type"] == "text":
                    parts.append(block["text"])
                elif vision:
                    parts.append("[image attached in the next message]")
                    pending_images.append({"type": "image_url", "image_url": {"url": f"data:{block['mime']};base64,{block['data']}"}})
                else:
                    parts.append(NO_VISION_NOTE)
            messages.append({"role": "tool", "tool_call_id": message["id"], "content": "\n".join(parts)})
    if pending_images:
        messages.append({"role": "user", "content": [{"type": "text", "text": "Images returned by the tools above."}] + pending_images})
    return messages


def _anthropic_block(block, vision):
    if block["type"] == "text":
        return {"type": "text", "text": block["text"]}
    if not vision:
        return {"type": "text", "text": NO_VISION_NOTE}
    return {"type": "image", "source": {"type": "base64", "media_type": block["mime"], "data": block["data"]}}


def anthropic_messages(history, vision):
    messages = []

    def add(role, blocks):
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": blocks})

    for message in history:
        if message["role"] == "user":
            add("user", [{"type": "text", "text": message["text"]}] + [
                {"type": "image", "source": {"type": "base64", "media_type": i["mime"], "data": i["data"]}}
                for i in (message.get("images") or []) if vision])
        elif message["role"] == "assistant":
            blocks = [{"type": "text", "text": message["text"]}] if message["text"] else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"] if c["arguments"] is not None else {}}
                       for c in message.get("tool_calls", [])]
            add("assistant", blocks or [{"type": "text", "text": "(no reply)"}])
        else:
            add("user", [{"type": "tool_result", "tool_use_id": message["id"], "is_error": message["is_error"],
                          "content": [_anthropic_block(b, vision) for b in message["content"]]}])
    return messages


class Provider:
    def __init__(self, base_url, api_key, model, vision=True, timeout=300):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.vision = vision
        self._timeout = timeout
        self._session = None

    async def close(self):
        if self._session is not None:
            await self._session.close()

    async def _post(self, url, headers, body):
        if self._session is None or self._session.closed:
            # trust_env=True so a configured HTTP(S)_PROXY is used to reach the API.
            self._session = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=self._timeout))
        try:
            async with self._session.post(url, headers=headers, json=body) as response:
                text = await response.text()
                status = response.status
        except aiohttp.ClientError as e:
            raise LLMError(f"Could not reach {url}: {e}") from e
        except asyncio.TimeoutError as e:
            raise LLMError(f"{url} did not answer within {self._timeout} seconds") from e
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if status >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            message = error.get("message") if isinstance(error, dict) else error or text[:300]
            raise LLMError(f"{status}: {message}")
        if data is None:
            raise LLMError(f"{url} answered with something that is not JSON: {text[:200]}")
        return data


class OpenAIProvider(Provider):
    async def complete(self, system, history, tools):
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": openai_messages(system, history, self.vision),
        }
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
        data = await self._post(self.base_url + "/chat/completions", headers, body)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Unexpected reply: {json.dumps(data, ensure_ascii=False)[:300]}") from e
        if not isinstance(message, dict) or not isinstance(message.get("content", "") or "", str):
            raise LLMError("Unexpected reply: assistant message must contain text")
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise LLMError("Unexpected reply: tool_calls must be a list")
        calls = []
        for call in tool_calls:
            if (not isinstance(call, dict) or not isinstance(call.get("id"), str)
                    or not isinstance(call.get("function"), dict)
                    or not isinstance(call["function"].get("name"), str)
                    or not isinstance(call["function"].get("arguments", "{}"), str)):
                raise LLMError("Unexpected reply: malformed tool call")
            raw = call["function"].get("arguments") or "{}"
            try:
                arguments = json.loads(raw)
            except ValueError:
                calls.append({"id": call["id"], "name": call["function"]["name"], "arguments": None, "raw_arguments": raw})
                continue
            calls.append({"id": call["id"], "name": call["function"]["name"], "arguments": arguments})
        return Reply(message.get("content") or "", calls, message.get("reasoning_content"))


class AnthropicProvider(Provider):
    async def complete(self, system, history, tools):
        url = self.base_url + ("/messages" if self.base_url.endswith("/v1") else "/v1/messages")
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        body = {"model": self.model, "max_tokens": 8192, "system": system, "messages": anthropic_messages(history, self.vision)}
        if tools:
            body["tools"] = tools
        data = await self._post(url, headers, body)
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            raise LLMError(f"Unexpected reply: {json.dumps(data, ensure_ascii=False)[:300]}")
        for block in blocks:
            if not isinstance(block, dict):
                raise LLMError("Unexpected reply: content block must be an object")
            if block.get("type") == "text" and not isinstance(block.get("text"), str):
                raise LLMError("Unexpected reply: text block is missing text")
            if block.get("type") == "tool_use" and (
                    not isinstance(block.get("id"), str) or not isinstance(block.get("name"), str)
                    or not isinstance(block.get("input"), dict)):
                raise LLMError("Unexpected reply: malformed tool use")
        text = "\n".join(b["text"] for b in blocks if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "arguments": b.get("input") or {}} for b in blocks if b.get("type") == "tool_use"]
        return Reply(text, calls)


def make_provider(config):
    cls = AnthropicProvider if config["format"] == "anthropic" else OpenAIProvider
    return cls(config["base_url"], config.get("api_key", ""), config["model"], config.get("vision", True))
