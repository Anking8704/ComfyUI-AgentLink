"""The chat agent: asks the model, runs the tools it calls, and repeats until it answers."""
import asyncio
from urllib.parse import urlencode

from .llm import LLMError
from .tools import ToolResult

CHAT_INSTRUCTIONS = """You are AgentLink, an assistant in a sidebar inside the user's ComfyUI. Reply in the language the user writes in (Chinese if they write Chinese), briefly; the bracketed canvas note is not theirs.

Work incrementally on the workflow the user has open, including an empty/incomplete graph. For a change or generation:
1. Call read_canvas each new turn to inspect actual nodes, named sockets, widget values and its target token.
2. Use patch_canvas(target, operations) for add/remove/connect/disconnect/set_widget edits on that graph. Reuse the
   target returned by each mutation; if stale, reread and reconsider the edit against the new state. Never retry a stale
   operation blindly. edit_canvas remains available for widget-only changes and participates in undo.
   Change only what the request needs. Preserve unrelated nodes, ids, positions, groups, quality tags, models and wiring.
   Discover installed node classes/options with search_nodes/get_node_schema and model paths with list_models.
   New nodes use temporary refs and exact named MODEL/CLIP sockets, not guessed numeric slots. Place them near related
   nodes. Unsupported subgraphs or custom/dynamic wiring need a clear explanation instead of rebuilding the graph.
   Use undo_canvas for an undo request. If manual edits followed an AgentLink edit, explain the protected undo refusal.
3. A modify-only request ends after the edit and a concise summary. Run only when the user explicitly asked to draw,
   generate or run. Then run_canvas and get_job(wait_seconds) until each job finishes. The user sees progress/images;
   get_image is only needed to judge a result. Never generate merely to test an edit.
Never save/open a replacement workflow to emulate an in-place edit. Use the normal search_nodes, get_node_schema,
validate_workflow, save_workflow, show_in_canvas flow when the user requests a new workflow or explicitly asks to open
a saved one. Saved workflows can still run directly with run_workflow(name, overrides).

For a named character, first search_character_loras using the character name and confirmed aliases, then installed
filenames as needed. This release uses local installed LoRAs only; no downloads. Exact names/aliases rank first, but
multiple candidate models/versions require the user's choice of exact model_path. Do not silently pick a version.
Call read_character for a selected candidate that has a saved record; filename-only matches have no record yet.
Use only user-confirmed triggers or explicit local JSON sidecar metadata, never generic training tag frequency.
trigger_words=null means unknown: ask the user for the triggers.
trigger_words=[] means the user confirmed none are needed. Never invent triggers or base-model compatibility.
When the user provides missing triggers/settings, save_character immediately without asking a second confirmation.
Save character, exact installed model_path, aliases, trigger_words, optional appearance_prompt, strengths, base_model
and provenance only as known. Updates merge supplied fields; aliases/trigger lists replace old lists, so include the
existing entries when adding new ones. Keep triggers separate from optional appearance and scene/outfit/action text.
Reuse the saved exact version and explicitly supplied strengths, including 0; null is unknown, not a default strength.
Add each trigger/appearance tag at most once to the existing prompt and preserve its quality tags and requested scene.
If a model is no longer installed, report it rather than substituting a similarly named model.
Apply the selected LoRA in place: update a suitable existing loader, or inspect LoraLoader's schema and add/wire a
compatible standard loader through patch_canvas. Establish the base model family and existing MODEL/CLIP source and
consumer sockets first. If compatibility or wiring cannot be established, report the uncertainty and ask for the
relevant information instead of blindly connecting. Show/list records on request with list_characters/read_character.
Reference images the user attaches come with their file names in ComfyUI's input folder. Use them as the request says:
describe or copy their look in the prompt, or set a LoadImage node to the file for img2img or image-guided workflows.
To find models use list_models with a query: base models may sit in checkpoints, diffusion_models or unet.
Use get_node_schema for a node's allowed options instead of guessing. If a run fails, tell the user what failed and how you
would fix it. Fix prompt or parameter mistakes yourself and retry once for an already requested generation; change a
model, CLIP, VAE or LoRA file only when the request or a prior explicit choice authorizes that exact change.
Call free_memory only when the user asks to free memory.
Write every reply, including the short line before a tool call, in the language of the user's latest message."""

# Added when the user turns on adult content. A plain statement of what is allowed; whether a model
# provider goes along with it is that provider's decision.
NSFW_INSTRUCTIONS = """
Adult content is enabled by the user, an adult running image models on their own computer. When they ask for explicit
images of adults, write the prompt plainly and specifically, in the style the workflow's model expects, without
euphemism, and keep the workflow's quality tags. Never create sexual content involving minors or characters who look underage."""

PAGE_TEXT_CHARS = 800


def _text_of(content):
    return "\n".join(block["text"] for block in content if block["type"] == "text")


class Agent:
    def __init__(self, provider, toolset, max_steps=30, max_tool_chars=30000, nsfw=False, page_tools=(), page_call=None):
        self.provider = provider
        self.toolset = toolset
        self.max_steps = max_steps
        self.max_tool_chars = max_tool_chars
        self.nsfw = nsfw
        self.page_tools = list(page_tools)
        self.page_call = page_call

    def _clip(self, content):
        clipped = []
        for block in content:
            if block["type"] == "text" and len(block["text"]) > self.max_tool_chars:
                cut = len(block["text"]) - self.max_tool_chars
                block = {"type": "text", "text": block["text"][:self.max_tool_chars] + f"\n...[truncated {cut} characters; narrow the query]"}
            clipped.append(block)
        return clipped

    async def _wait(self, operation, stop):
        task = asyncio.create_task(operation)
        stopping = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait((task, stopping), return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise InterruptedError()
            return await task
        finally:
            stopping.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, stopping, return_exceptions=True)

    async def run(self, history, text, stop, images=None):
        try:
            async for event in self._run(history, text, stop, images):
                yield event
        finally:
            pending = {}
            for message in history:
                if message["role"] == "assistant":
                    for call in message.get("tool_calls", []):
                        pending[call["id"]] = call
                elif message["role"] == "tool":
                    pending.pop(message["id"], None)
            for call in pending.values():
                history.append({"role": "tool", "id": call["id"], "name": call["name"], "is_error": True,
                                "content": [{"type": "text", "text": "Cancelled by the user."}]})

    async def _run(self, history, text, stop, images=None):
        """Append one user turn to history and yield events for the page until the model is done."""
        history.append({"role": "user", "text": text, **({"images": images} if images else {})})
        schemas = self.page_tools + self.toolset.schemas()
        page_names = {tool["name"] for tool in self.page_tools}
        instructions = CHAT_INSTRUCTIONS + (NSFW_INSTRUCTIONS if self.nsfw else "")
        for _ in range(self.max_steps):
            if stop.is_set():
                yield {"type": "done", "stopped": True}
                return
            try:
                reply = await self._wait(self.provider.complete(instructions, history, schemas), stop)
            except InterruptedError:
                yield {"type": "done", "stopped": True}
                return
            except LLMError as e:
                yield {"type": "error", "message": str(e)}
                yield {"type": "done", "stopped": False}
                return
            history.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls, "reasoning": reply.reasoning})
            if reply.text:
                yield {"type": "text", "text": reply.text}
            if not reply.tool_calls:
                yield {"type": "done", "stopped": False}
                return
            for call in reply.tool_calls:
                if stop.is_set():
                    # Every tool call needs an answer or the next request is rejected.
                    history.append({"role": "tool", "id": call["id"], "name": call["name"], "is_error": True,
                                    "content": [{"type": "text", "text": "Cancelled by the user."}]})
                    continue
                yield {"type": "tool_call", "id": call["id"], "name": call["name"], "arguments": call["arguments"]}
                if call["arguments"] is None:
                    result = ToolResult.error(f"The arguments were not valid JSON: {call.get('raw_arguments', '')[:200]}")
                else:
                    try:
                        result = await self._wait(self._call_tool(call, page_names), stop)
                    except InterruptedError:
                        result = ToolResult.error("Cancelled by the user.")
                history.append({"role": "tool", "id": call["id"], "name": call["name"], "is_error": result.is_error, "content": self._clip(result.content)})
                yield self._result_event(call, result)
                if result.event:
                    yield result.event
        yield {"type": "error", "message": f"Stopped after {self.max_steps} steps without finishing. Ask again to continue."}
        yield {"type": "done", "stopped": False}

    async def _call_tool(self, call, page_names):
        if call["name"] not in page_names:
            return await self.toolset.call(call["name"], call["arguments"])
        try:
            return ToolResult.of(await self.page_call(call))
        except Exception as e:
            return ToolResult.error(f"{call['name']}: {e}")

    def _result_event(self, call, result):
        event = {"type": "tool_result", "id": call["id"], "name": call["name"], "is_error": result.is_error,
                 "text": _text_of(result.content)[:PAGE_TEXT_CHARS]}
        image = next((b for b in result.content if b["type"] == "image"), None)
        if image:
            event["image"] = f"data:{image['mime']};base64,{image['data']}"
            args = call["arguments"]
            event["view"] = "/view?" + urlencode({"filename": args.get("filename", ""), "subfolder": args.get("subfolder", ""), "type": args.get("type", "output")})
        return event
