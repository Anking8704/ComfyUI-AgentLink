import asyncio

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
