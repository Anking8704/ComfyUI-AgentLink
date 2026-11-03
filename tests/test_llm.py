import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from agentlink.llm import AnthropicProvider, LLMError, OpenAIProvider, anthropic_messages, make_provider, openai_messages

IMAGE = {"type": "image", "data": "QUJD", "mime": "image/jpeg"}
TOOLS = [{"name": "get_job", "description": "Get a job", "input_schema": {"type": "object", "properties": {"prompt_id": {"type": "string"}}, "required": ["prompt_id"]}}]

HISTORY = [
    {"role": "user", "text": "draw a cat"},
    {"role": "assistant", "text": "Checking.", "tool_calls": [{"id": "c1", "name": "get_job", "arguments": {"prompt_id": "a"}}, {"id": "c2", "name": "get_image", "arguments": {}}]},
    {"role": "tool", "id": "c1", "name": "get_job", "is_error": False, "content": [{"type": "text", "text": "{\"status\": \"completed\"}"}]},
    {"role": "tool", "id": "c2", "name": "get_image", "is_error": False, "content": [IMAGE]},
    {"role": "assistant", "text": "Here it is.", "tool_calls": []},
]


def test_openai_history_with_tool_calls_and_images():
    messages = openai_messages("sys", HISTORY, vision=True)
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "draw a cat"}
    assert messages[2]["tool_calls"][0] == {"id": "c1", "type": "function", "function": {"name": "get_job", "arguments": "{\"prompt_id\": \"a\"}"}}
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"status\": \"completed\"}"}
    assert messages[4]["role"] == "tool" and "image" in messages[4]["content"]
    assert messages[5]["role"] == "user"
    assert messages[5]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}
    assert messages[6] == {"role": "assistant", "content": "Here it is."}


def test_openai_without_vision_drops_images():
    messages = openai_messages("sys", HISTORY, vision=False)
    assert all(m["role"] != "user" or isinstance(m["content"], str) for m in messages)
    assert "cannot view images" in messages[4]["content"]


def test_openai_passes_reasoning_back():
    messages = openai_messages("sys", [{"role": "assistant", "text": "", "tool_calls": [], "reasoning": "think"}], vision=True)
    assert messages[1] == {"role": "assistant", "content": None, "reasoning_content": "think"}


def test_anthropic_groups_tool_results_into_one_user_turn():
    messages = anthropic_messages(HISTORY, vision=True)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "get_job", "input": {"prompt_id": "a"}}
    results = messages[2]["content"]
    assert results[0]["tool_use_id"] == "c1" and results[0]["is_error"] is False
    assert results[1]["content"] == [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}]


def test_anthropic_merges_a_user_message_after_tool_results():
    history = HISTORY[:4] + [{"role": "user", "text": "again"}]
    messages = anthropic_messages(history, vision=True)
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"][-1] == {"type": "text", "text": "again"}


def test_anthropic_without_vision_replaces_image_with_note():
    results = anthropic_messages(HISTORY, vision=False)[2]["content"]
    assert results[1]["content"][0]["type"] == "text"


def test_make_provider_picks_format():
    assert isinstance(make_provider({"format": "openai", "base_url": "x", "api_key": "", "model": "m"}), OpenAIProvider)
    assert isinstance(make_provider({"format": "anthropic", "base_url": "x", "api_key": "k", "model": "m"}), AnthropicProvider)


class FakeLLM:
    def __init__(self, response, status=200):
        self.response, self.status, self.requests = response, status, []

    async def handle(self, request):
        self.requests.append({"path": request.path, "headers": dict(request.headers), "body": await request.json()})
        return web.json_response(self.response, status=self.status)


@pytest.fixture
async def fake_llm():
    servers = []

    async def start(response, status=200):
        fake = FakeLLM(response, status)
        app = web.Application()
        app.router.add_post("/{tail:.*}", fake.handle)
        server = TestServer(app)
        await server.start_server()
        servers.append(server)
        return fake, str(server.make_url("")).rstrip("/")

    yield start
    for server in servers:
        await server.close()


async def test_openai_request_and_tool_call_parsing(fake_llm):
    fake, url = await fake_llm({"choices": [{"message": {"content": None, "reasoning_content": "hmm", "tool_calls": [
        {"id": "c9", "type": "function", "function": {"name": "get_job", "arguments": "{\"prompt_id\": \"z\"}"}}]}, "finish_reason": "tool_calls"}]})
    provider = OpenAIProvider(url + "/v1", "sk-test", "deepseek-chat")
    reply = await provider.complete("sys", [{"role": "user", "text": "hi"}], TOOLS)
    await provider.close()
    request = fake.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-test"
    assert request["body"]["model"] == "deepseek-chat"
    assert request["body"]["tools"][0] == {"type": "function", "function": {"name": "get_job", "description": "Get a job", "parameters": TOOLS[0]["input_schema"]}}
    assert reply.tool_calls == [{"id": "c9", "name": "get_job", "arguments": {"prompt_id": "z"}}]
    assert reply.reasoning == "hmm"


async def test_openai_without_key_sends_no_auth_header(fake_llm):
    fake, url = await fake_llm({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    provider = OpenAIProvider(url, "", "llama")
    reply = await provider.complete("sys", [{"role": "user", "text": "hi"}], TOOLS)
    await provider.close()
    assert "Authorization" not in fake.requests[0]["headers"]
    assert reply.text == "ok" and reply.tool_calls == []


async def test_openai_bad_tool_arguments_are_kept_for_the_agent_to_report(fake_llm):
    fake, url = await fake_llm({"choices": [{"message": {"tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "get_job", "arguments": "{oops"}}]}}]})
    provider = OpenAIProvider(url, "k", "m")
    reply = await provider.complete("sys", [{"role": "user", "text": "hi"}], TOOLS)
    await provider.close()
    assert reply.tool_calls[0]["arguments"] is None
    assert reply.tool_calls[0]["raw_arguments"] == "{oops"


async def test_anthropic_request_and_parsing(fake_llm):
    fake, url = await fake_llm({"content": [{"type": "text", "text": "Let me check."},
                                            {"type": "tool_use", "id": "t1", "name": "get_job", "input": {"prompt_id": "q"}}], "stop_reason": "tool_use"})
    provider = AnthropicProvider(url, "sk-ant", "claude-x")
    reply = await provider.complete("sys", [{"role": "user", "text": "hi"}], TOOLS)
    await provider.close()
    request = fake.requests[0]
    assert request["path"] == "/v1/messages"
    assert request["headers"]["x-api-key"] == "sk-ant"
    assert request["body"]["system"] == "sys"
    assert request["body"]["tools"] == TOOLS
    assert reply.text == "Let me check."
    assert reply.tool_calls == [{"id": "t1", "name": "get_job", "arguments": {"prompt_id": "q"}}]


async def test_api_errors_carry_the_provider_message(fake_llm):
    fake, url = await fake_llm({"error": {"message": "Invalid API key"}}, status=401)
    provider = OpenAIProvider(url, "bad", "m")
    with pytest.raises(LLMError, match="401.*Invalid API key"):
        await provider.complete("sys", [{"role": "user", "text": "hi"}], TOOLS)
    await provider.close()


async def test_unreachable_api_is_an_llm_error():
    provider = OpenAIProvider("http://127.0.0.1:9", "k", "m")
    with pytest.raises(LLMError, match="reach"):
        await provider.complete("sys", [{"role": "user", "text": "hi"}], TOOLS)
    await provider.close()


REF = {"data": "UkVG", "mime": "image/png"}


def test_openai_user_reference_images_ride_along_with_vision():
    messages = openai_messages("sys", [{"role": "user", "text": "like this", "images": [REF]}], vision=True)
    assert messages[1]["content"] == [{"type": "text", "text": "like this"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,UkVG"}}]


def test_openai_user_reference_images_are_left_out_without_vision():
    assert openai_messages("sys", [{"role": "user", "text": "like this", "images": [REF]}], vision=False)[1] == {"role": "user", "content": "like this"}


def test_anthropic_user_reference_images():
    blocks = anthropic_messages([{"role": "user", "text": "like this", "images": [REF]}], vision=True)[0]["content"]
    assert blocks == [{"type": "text", "text": "like this"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "UkVG"}}]

@pytest.mark.parametrize('cls,payload', [
    (OpenAIProvider, {'choices':[{'message':None}]}),
    (OpenAIProvider, {'choices':[{'message':{'content':42}}]}),
    (OpenAIProvider, {'choices':[{'message':{'tool_calls':[{'id':'x','function':{'name':'tool','arguments':{}}}]}}]}),
    (AnthropicProvider, []),
    (AnthropicProvider, {'content':[{'type':'text'}]}),
])
async def test_malformed_provider_reply_reports_llm_error(cls, payload):
    from unittest.mock import AsyncMock
    provider = cls('http://unused', '', 'test')
    provider._post = AsyncMock(return_value=payload)
    with pytest.raises(LLMError):
        await provider.complete('test', [], [])
