import asyncio
import json

from agentlink.agent import Agent
from agentlink.llm import LLMError, Reply


class ScriptedProvider:
    """Plays back replies in order and records what the agent sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(id, name, arguments):
    return {"id": id, "name": name, "arguments": arguments}


async def collect(agent, history, text, stop=None):
    return [event async for event in agent.run(history, text, stop or asyncio.Event())]


async def test_plain_answer(toolset):
    provider = ScriptedProvider(Reply("Hello!", []))
    history = []
    events = await collect(Agent(provider, toolset), history, "hi")
    assert events == [{"type": "text", "text": "Hello!"}, {"type": "done", "stopped": False}]
    assert history == [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "Hello!", "tool_calls": [], "reasoning": None}]


async def test_tool_round_trip_reaches_the_model_and_the_page(toolset):
    provider = ScriptedProvider(Reply("Checking.", [call("c1", "list_models", {"folder": "loras"})]), Reply("You have 2 LoRAs.", []))
    history = []
    events = await collect(Agent(provider, toolset), history, "my loras?")
    kinds = [e["type"] for e in events]
    assert kinds == ["text", "tool_call", "tool_result", "text", "done"]
    assert events[1] == {"type": "tool_call", "id": "c1", "name": "list_models", "arguments": {"folder": "loras"}}
    assert events[2]["is_error"] is False and "Style_A" in events[2]["text"]
    tool_message = provider.calls[1]["messages"][2]
    assert tool_message["role"] == "tool" and tool_message["id"] == "c1"


async def test_images_go_to_the_page_as_data_urls(toolset):
    provider = ScriptedProvider(Reply("", [call("c1", "get_image", {"filename": "x.png"})]), Reply("Done.", []))
    events = await collect(Agent(provider, toolset), [], "show")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["image"].startswith("data:image/jpeg;base64,")
    assert result["view"] == "/view?filename=x.png&subfolder=&type=output"


async def test_tool_events_are_forwarded(client, comfy):
    from agentlink.tools import Toolset
    chat = Toolset(client, chat=True)
    provider = ScriptedProvider(Reply("", [call("c1", "show_in_canvas", {"name": "sub/ui file.json"})]), Reply("Opened.", []))
    events = await collect(Agent(provider, chat), [], "open it")
    opened = next(e for e in events if e["type"] == "open_workflow")
    assert opened["name"] == "sub/ui file.json"


async def test_unparseable_arguments_are_reported_to_the_model(toolset):
    bad = {"id": "c1", "name": "list_models", "arguments": None, "raw_arguments": "{oops"}
    provider = ScriptedProvider(Reply("", [bad]), Reply("Sorry.", []))
    events = await collect(Agent(provider, toolset), [], "x")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["is_error"] and "not valid JSON" in result["text"]


async def test_model_errors_end_the_turn_with_an_error_event(toolset):
    provider = ScriptedProvider(LLMError("401: Invalid API key"))
    events = await collect(Agent(provider, toolset), [], "hi")
    assert events == [{"type": "error", "message": "401: Invalid API key"}, {"type": "done", "stopped": False}]


async def test_stop_cancels_remaining_tool_calls_but_keeps_history_valid(toolset):
    stop = asyncio.Event()
    provider = ScriptedProvider(Reply("", [call("c1", "list_models", {}), call("c2", "list_models", {})]))
    history = []
    events = []
    async for event in Agent(provider, toolset).run(history, "go", stop):
        events.append(event)
        if event["type"] == "tool_result":
            stop.set()
    assert events[-1] == {"type": "done", "stopped": True}
    tool_messages = [m for m in history if m["role"] == "tool"]
    assert [m["id"] for m in tool_messages] == ["c1", "c2"]
    assert "Cancelled" in tool_messages[1]["content"][0]["text"]


async def test_step_limit(toolset):
    provider = ScriptedProvider(*[Reply("", [call(f"c{i}", "list_models", {})]) for i in range(3)])
    events = await collect(Agent(provider, toolset, max_steps=2), [], "loop")
    assert events[-2]["type"] == "error" and "2 steps" in events[-2]["message"]


async def test_long_tool_output_is_cut_before_reaching_the_model(toolset, comfy):
    comfy.object_info = {f"Node{i}": {"display_name": "x" * 50, "category": "c", "python_module": "m", "input": {}, "output": []} for i in range(2000)}
    provider = ScriptedProvider(Reply("", [call("c1", "search_nodes", {"query": "node", "limit": 2000})]), Reply("ok", []))
    await collect(Agent(provider, toolset, max_tool_chars=1000), [], "x")
    text = provider.calls[1]["messages"][2]["content"][0]["text"]
    assert len(text) < 1200 and "truncated" in text

async def test_stop_interrupts_model_wait(toolset):
    started = asyncio.Event()
    class Slow:
        async def complete(self, *args):
            started.set()
            await asyncio.Event().wait()
    stop = asyncio.Event()
    task = asyncio.create_task(collect(Agent(Slow(), toolset), [], 'hello', stop))
    await started.wait()
    stop.set()
    events = await asyncio.wait_for(task, .5)
    assert events[-1] == {'type': 'done', 'stopped': True}

async def test_adult_content_note_is_off_unless_asked(toolset):
    provider = ScriptedProvider(Reply("ok", []))
    await collect(Agent(provider, toolset), [], "draw a cat")
    assert "adult content" not in provider.calls[0]["system"].lower()


async def test_adult_content_setting_is_a_plain_instruction(toolset):
    provider = ScriptedProvider(Reply("ok", []))
    history = []
    await collect(Agent(provider, toolset, nsfw=True), history, "draw a cat")
    system = provider.calls[0]["system"]
    assert "adult content" in system.lower() and "minor" in system.lower()
    # Nothing is slipped into the conversation the model sees.
    assert provider.calls[0]["messages"] == [{"role": "user", "text": "draw a cat"}]


CANVAS_TOOL = {"name": "read_canvas", "description": "Read the canvas", "input_schema": {"type": "object", "properties": {}, "required": []}}


async def test_browser_tools_are_offered_first_and_answered_by_the_page(toolset):
    asked = []

    async def page(call):
        asked.append(call)
        return {"nodes": [{"id": "5", "class_type": "CLIPTextEncode"}]}

    provider = ScriptedProvider(Reply("", [call("c1", "read_canvas", {})]), Reply("Read it.", []))
    history = []
    events = await collect(Agent(provider, toolset, page_tools=[CANVAS_TOOL], page_call=page), history, "what is open?")
    assert provider.calls[0]["tools"][0]["name"] == "read_canvas"
    assert asked == [{"id": "c1", "name": "read_canvas", "arguments": {}}]
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "text", "done"]
    assert "CLIPTextEncode" in history[2]["content"][0]["text"]


async def test_page_tool_failures_reach_the_model(toolset):
    async def page(call):
        raise RuntimeError("Node 99 is not on the canvas")

    provider = ScriptedProvider(Reply("", [call("c1", "read_canvas", {})]), Reply("ok", []))
    events = await collect(Agent(provider, toolset, page_tools=[CANVAS_TOOL], page_call=page), [], "x")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["is_error"] and "Node 99" in result["text"]


async def test_reference_images_are_kept_on_the_user_turn(toolset):
    provider = ScriptedProvider(Reply("ok", []))
    history = []
    await collect_with_images(Agent(provider, toolset), history, "like this", [{"data": "UkVG", "mime": "image/png"}])
    assert history[0] == {"role": "user", "text": "like this", "images": [{"data": "UkVG", "mime": "image/png"}]}


async def collect_with_images(agent, history, text, images):
    return [event async for event in agent.run(history, text, asyncio.Event(), images=images)]


async def test_character_followup_save_read_and_inplace_patch_preserves_exact_record_and_target(client, comfy, tmp_path):
    from agentlink.characters import CharacterStore
    from agentlink.tools import PAGE_TOOLS, Toolset

    exact_path = r"characters\Hero-v2.safetensors"
    comfy.model_files["loras"] = [exact_path]
    store = CharacterStore(tmp_path / "agentlink" / "characters.json")
    toolset = Toolset(client, chat=True, characters=store)
    record = {"character": "Hero", "aliases": ["勇者"], "model_path": exact_path,
              "trigger_words": ["hero_token"], "strength_model": 0, "strength_clip": 0}
    operations = [{"op": "set_widget", "node": "11", "widget": "lora_name", "value": exact_path},
                  {"op": "set_widget", "node": "11", "widget": "strength_model", "value": 0},
                  {"op": "set_widget", "node": "11", "widget": "strength_clip", "value": 0},
                  {"op": "set_widget", "node": "6", "widget": "text", "value": "quality, hero_token, beach"}]
    provider = ScriptedProvider(
        Reply("", [call("find", "search_character_loras", {"query": "Hero"})]),
        Reply("这个版本的触发词是什么？", []),
        Reply("", [call("save", "save_character", {"record": record})]),
        Reply("", [call("read", "read_character", {"character": "勇者", "model_path": exact_path})]),
        Reply("", [call("canvas", "read_canvas", {})]),
        Reply("", [call("patch", "patch_canvas", {"target": "inspected-root-7", "operations": operations})]),
        Reply("已记住并修改。", []))
    page_calls = []

    async def page(request):
        page_calls.append(request)
        if request["name"] == "read_canvas":
            return {"target": "inspected-root-7", "nodes": [
                {"id": "11", "class_type": "LoraLoader", "values": {"lora_name": exact_path}},
                {"id": "6", "class_type": "CLIPTextEncode", "values": {"text": "quality, beach"}}]}
        if request["name"] == "patch_canvas":
            return {"applied": 4, "target": "mutated-root-8", "undo_available": 1}
        raise AssertionError(f"unexpected page operation: {request['name']}")

    agent = Agent(provider, toolset, page_tools=PAGE_TOOLS, page_call=page)
    history = []
    first = await collect(agent, history, "查找 Hero 的 LoRA，先不要生成")
    assert first[-2]["text"] == "这个版本的触发词是什么？"
    discovery = json.loads(provider.calls[1]["messages"][2]["content"][0]["text"])
    assert discovery["candidates"][0]["model_path"] == exact_path
    assert discovery["candidates"][0]["record"] is None
    assert not store.path.exists(), "lookup alone must not invent a record or triggers"
    second = await collect(agent, history, "触发词是 hero_token，记住别名勇者，两种强度都用 0；修改画布但不要运行")
    assert not any(e.get("is_error") for e in second)
    assert page_calls[-1]["arguments"] == {"target": "inspected-root-7", "operations": operations}
    final_messages = provider.calls[-1]["messages"]
    by_id = {m["id"]: json.loads(m["content"][0]["text"]) for m in final_messages if m["role"] == "tool"}
    assert by_id["read"]["model_path"] == exact_path
    assert by_id["read"]["strength_model"] == by_id["read"]["strength_clip"] == 0
    assert by_id["read"]["trigger_words"] == ["hero_token"]
    assert by_id["canvas"]["target"] == "inspected-root-7"
    assert by_id["patch"]["target"] == "mutated-root-8"
    assert [c["name"] for c in page_calls] == ["read_canvas", "patch_canvas"]
    assert not any(e.get("name") in {"run_canvas", "run_workflow", "show_in_canvas"} or e["type"] == "open_workflow" for e in first + second)
    assert not comfy.posts
    assert CharacterStore(store.path).read("勇者")["trigger_words"] == ["hero_token"]
