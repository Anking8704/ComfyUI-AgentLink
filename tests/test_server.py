import asyncio
import json
from unittest import mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from mcp import Client

from agentlink.llm import LLMError, Reply
from agentlink.server import AgentLinkServer, ConfigStore, is_local_request


class ScriptedProvider:
    def __init__(self, *replies):
        self.replies = list(replies)

    async def complete(self, system, messages, tools):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def close(self):
        pass


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "agentlink" / "config.json")


@pytest.fixture
async def http(client, store):
    providers = []
    server = AgentLinkServer(client, store, provider_factory=lambda config: providers.pop(0))
    routes = web.RouteTableDef()
    server.add_routes(routes)
    app = web.Application()
    app.add_routes(routes)
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    test_client.providers = providers
    yield test_client
    await test_client.close()


def peer(address, origin=None, content_type="application/json"):
    transport = mock.Mock()
    transport.get_extra_info.return_value = (address, 50000)
    headers = {"Content-Type": content_type}
    if origin:
        headers["Origin"] = origin
    return make_mocked_request("POST", "/agentlink/chat", headers=headers, transport=transport)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_local_requests_pass(address):
    assert is_local_request(peer(address)) is None


def test_other_computers_are_refused():
    assert "this computer" in is_local_request(peer("10.200.42.7"))


def test_foreign_web_pages_are_refused():
    assert "page" in is_local_request(peer("127.0.0.1", origin="https://evil.example"))


def test_comfyui_page_on_this_computer_passes():
    assert is_local_request(peer("127.0.0.1", origin="http://127.0.0.1:8188")) is None


def test_posts_must_be_json():
    assert "JSON" in is_local_request(peer("127.0.0.1", content_type="text/plain"))


async def test_config_never_returns_the_key(http, store):
    response = await http.post("/agentlink/config", json={"format": "openai", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": "sk-1234567890abcd"})
    config = await response.json()
    assert "api_key" not in config
    assert config["has_key"] is True and config["key_hint"] == "sk-…abcd"
    assert store.load()["api_key"] == "sk-1234567890abcd"


async def test_saving_without_a_key_keeps_the_old_one(http, store):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "sk-old-key-1111"})
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m2"})
    assert store.load()["api_key"] == "sk-old-key-1111"
    assert store.load()["model"] == "m2"


async def test_config_rejects_unknown_format(http):
    response = await http.post("/agentlink/config", json={"format": "gemini", "base_url": "u", "model": "m"})
    assert response.status == 400


async def chat_events(http, session, text):
    response = await http.post("/agentlink/chat", json={"session": session, "text": text})
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    body = await response.text()
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


async def test_chat_without_settings_explains_what_to_do(http):
    events = await chat_events(http, "s1", "hi")
    assert events[0]["type"] == "error" and "API" in events[0]["message"]


async def test_chat_streams_agent_events_and_keeps_history(http):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k"})
    http.providers.append(ScriptedProvider(Reply("", [{"id": "c1", "name": "list_models", "arguments": {}}]), Reply("Done.", []), Reply("Again.", [])))
    events = await chat_events(http, "s1", "hi")
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "text", "done"]
    events = await chat_events(http, "s1", "more")
    assert {k: v for k, v in events[0].items() if k != "seq"} == {"type": "text", "text": "Again."}


async def test_reset_clears_history(http):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k"})
    http.providers.append(ScriptedProvider(Reply("one", []), Reply("two", [])))
    await chat_events(http, "s1", "hi")
    response = await http.post("/agentlink/reset", json={"session": "s1"})
    assert (await response.json()) == {"reset": True}


async def test_connection_test_reports_model_errors(http):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k"})
    http.providers.append(ScriptedProvider(LLMError("401: Invalid API key")))
    result = await (await http.post("/agentlink/test", json={})).json()
    assert result == {"ok": False, "error": "401: Invalid API key"}


async def test_connection_test_success(http):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k"})
    http.providers.append(ScriptedProvider(Reply("OK", [])))
    assert (await (await http.post("/agentlink/test", json={})).json()) == {"ok": True, "reply": "OK"}


async def test_info_tells_the_page_where_mcp_lives(http):
    info = await (await http.get("/agentlink/info")).json()
    assert info["mcp_path"] == "/agentlink/mcp"
    assert info["local"] is True


async def test_official_mcp_client_can_list_and_call_tools(http):
    url = str(http.make_url("/agentlink/mcp"))
    async with Client(url) as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool("list_models", {"folder": "loras"})
        failed = await session.call_tool("get_node_schema", {"class_type": "Nope"})
    assert "run_workflow" in tools and "show_in_canvas" not in tools
    assert "Style_A" in result.content[0].text and not result.is_error
    assert failed.is_error and "search_nodes" in failed.content[0].text


async def test_mcp_images_use_mcp_block_shape(http):
    response = await http.post("/agentlink/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_image", "arguments": {"filename": "x.png"}}})
    block = (await response.json())["result"]["content"][0]
    assert block["type"] == "image" and block["mimeType"] == "image/jpeg"


async def test_mcp_unknown_method(http):
    response = await http.post("/agentlink/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
    assert (await response.json())["error"]["code"] == -32601


async def test_mcp_notifications_get_no_body(http):
    response = await http.post("/agentlink/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status == 202

async def test_nsfw_preset_is_saved_and_sent_with_the_chat(http, store):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k", "nsfw": True})
    assert store.load()["nsfw"] is True
    seen = {}

    class RecordingProvider(ScriptedProvider):
        async def complete(self, system, messages, tools):
            seen["system"] = system
            return await super().complete(system, messages, tools)

    http.providers.append(RecordingProvider(Reply("ok", [])))
    await chat_events(http, "s1", "hi")
    assert "adult content" in seen["system"].lower()


async def test_nsfw_preset_defaults_off_for_an_old_config(store):
    store.save({"format": "openai", "base_url": "u", "model": "m", "api_key": "k", "vision": True})
    assert store.load()["nsfw"] is False


async def test_changing_provider_clears_key(http, store):
    await http.post('/agentlink/config', json={'format':'openai','base_url':'https://a.example/v1','model':'m','api_key':'secret'})
    await http.post('/agentlink/config', json={'format':'openai','base_url':'https://b.example/v1','model':'m'})
    assert store.load()['api_key'] == ''

async def test_retired_provider_waits_for_all_users():
    from unittest.mock import AsyncMock
    from agentlink.server import AgentLinkServer
    old, new = AsyncMock(), AsyncMock()
    choices = iter([old, new])
    server = AgentLinkServer(None, None, provider_factory=lambda c: next(choices))
    await server._get_provider({'model': 'a'})
    await server._get_provider({'model': 'a'})
    await server._get_provider({'model': 'b'})
    await server._release_provider(old)
    old.close.assert_not_awaited()
    await server._release_provider(old)
    old.close.assert_awaited_once()
    await server._release_provider(new)


class Recording(ScriptedProvider):
    def __init__(self, *replies):
        super().__init__(*replies)
        self.seen = []

    async def complete(self, system, messages, tools):
        self.seen.append({"messages": [dict(m) for m in messages], "tools": [t["name"] for t in tools]})
        return await super().complete(system, messages, tools)


async def configure(http):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k"})


async def test_chat_saves_character_followup_mcp_reads_it_after_fresh_server(http, store, client):
    await configure(http)
    provider = Recording(Reply("触发词是什么？", []), Reply("", [{"id": "save", "name": "save_character", "arguments": {
        "record": {"character": "Hero", "model_path": "Style_A.safetensors", "aliases": ["勇者"],
                   "trigger_words": ["hero_token"], "strength_model": 0, "strength_clip": 0}}}]), Reply("已记住。", []))
    http.providers.append(provider)
    await chat_events(http, "character", "记住勇者使用 Style_A.safetensors")
    events = await chat_events(http, "character", "触发词是 hero_token，两个强度都是 0")
    assert not next(e for e in events if e["type"] == "tool_result")["is_error"]
    assert {"read_canvas", "patch_canvas", "undo_canvas", "save_character", "search_character_loras"} <= set(provider.seen[0]["tools"])
    assert all(e.get("name") != "run_canvas" for e in events)
    fresh = AgentLinkServer(client, ConfigStore(store.path))
    routes = web.RouteTableDef()
    fresh.add_routes(routes)
    app = web.Application()
    app.add_routes(routes)
    async with TestClient(TestServer(app)) as restarted:
        listing = await restarted.post("/agentlink/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in (await listing.json())["result"]["tools"]}
        assert {"list_characters", "search_character_loras", "read_character", "save_character"} <= names
        assert not {"read_canvas", "patch_canvas", "undo_canvas", "show_in_canvas", "run_canvas"} & names
        read = await restarted.post("/agentlink/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "read_character", "arguments": {"character": "勇者"}}})
        result = (await read.json())["result"]
        assert not result["isError"]
        record = json.loads(result["content"][0]["text"])
        assert record["trigger_words"] == ["hero_token"]
        assert record["strength_model"] == record["strength_clip"] == 0
        assert fresh.characters.path == store.path.with_name("characters.json")


async def test_character_mcp_write_rejects_foreign_origin_without_creating_storage(http, store):
    result = await http.post("/agentlink/mcp", headers={"Origin": "https://foreign.example"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "save_character", "arguments": {
            "record": {"character": "Hero", "model_path": "Style_A.safetensors"}}}})
    assert result.status == 403
    assert not store.path.with_name("characters.json").exists()


async def test_chat_tells_the_model_what_is_open_on_the_canvas(http):
    await configure(http)
    provider = Recording(Reply("ok", []))
    http.providers.append(provider)
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "draw a cat",
                                                       "canvas": {"name": "Anima.json", "nodes": 10, "types": ["KSampler", "CLIPTextEncode"]}})
    await response.text()
    sent = provider.seen[0]["messages"][-1]["text"]
    assert sent.startswith("draw a cat") and "Anima.json" in sent and "read_canvas" in sent
    assert provider.seen[0]["tools"][:3] == ["read_canvas", "edit_canvas", "run_canvas"]


async def test_page_answers_browser_tool_calls(http):
    await configure(http)
    http.providers.append(Recording(Reply("", [{"id": "c1", "name": "read_canvas", "arguments": {}}]), Reply("It has a sampler.", [])))
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "what is open?"})
    events = []
    while True:
        line = (await response.content.readline()).decode()
        if not line:
            break
        if line.startswith("data: "):
            event = json.loads(line[6:])
            events.append(event)
            if event["type"] == "tool_call":
                answer = await http.post("/agentlink/page_result", json={"session": "s1", "id": "c1", "result": {"nodes": [{"id": "3", "class_type": "KSampler"}]}})
                assert (await answer.json()) == {"accepted": True}
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "text", "done"]
    assert "KSampler" in events[1]["text"]


async def test_page_results_for_unknown_calls_are_refused(http):
    answer = await http.post("/agentlink/page_result", json={"session": "nope", "id": "c1", "result": {}})
    assert (await answer.json()) == {"accepted": False}


PNG_B64 = "iVBORw0KGgo="


async def test_reference_images_reach_the_model_with_their_comfyui_names(http):
    await configure(http)
    provider = Recording(Reply("ok", []))
    http.providers.append(provider)
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "like this",
                                                       "images": [{"data": PNG_B64, "mime": "image/png", "name": "ref (1).png"}]})
    await response.text()
    sent = provider.seen[0]["messages"][-1]
    assert sent["images"] == [{"data": PNG_B64, "mime": "image/png"}]
    assert "ref (1).png" in sent["text"] and "LoadImage" in sent["text"]


async def test_non_vision_models_are_told_to_use_the_tagger(http):
    await http.post("/agentlink/config", json={"format": "openai", "base_url": "u", "model": "m", "api_key": "k", "vision": False})
    provider = Recording(Reply("ok", []))
    http.providers.append(provider)
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "like this", "images": [{"data": PNG_B64, "mime": "image/png", "name": "ref.png"}]})
    await response.text()
    assert "describe_image" in provider.seen[0]["messages"][-1]["text"]


@pytest.mark.parametrize("images", [
    [{"data": PNG_B64, "mime": "text/html", "name": "x"}],
    [{"data": PNG_B64, "mime": "image/png", "name": "x"}] * 5,
])
async def test_bad_reference_images_are_refused(http, images):
    await configure(http)
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "x", "images": images})
    assert response.status == 400


async def test_images_alone_are_a_valid_message(http):
    await configure(http)
    http.providers.append(Recording(Reply("ok", [])))
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "", "images": [{"data": PNG_B64, "mime": "image/png", "name": "ref.png"}]})
    assert response.status == 200


class GatedProvider(ScriptedProvider):
    """Holds its second reply until the test opens the gate, like a slow model while the phone is away."""
    def __init__(self, *replies):
        super().__init__(*replies)
        self.gate = asyncio.Event()
        self.calls = 0

    async def complete(self, system, messages, tools):
        self.calls += 1
        if self.calls == 2:
            await self.gate.wait()
        return await super().complete(system, messages, tools)


async def read_until(response, kind):
    events = []
    while True:
        line = (await response.content.readline()).decode()
        if not line:
            return events
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
            if events[-1]["type"] == kind:
                return events


async def test_a_turn_keeps_running_after_the_page_disconnects_and_can_be_resumed(http):
    await configure(http)
    provider = GatedProvider(Reply("", [{"id": "c1", "name": "list_models", "arguments": {}}]), Reply("Finished while you were away.", []))
    http.providers.append(provider)
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "hi"})
    first = await read_until(response, "tool_result")
    assert [e["seq"] for e in first] == [1, 2]
    response.close()  # the phone locks its screen
    provider.gate.set()
    for _ in range(50):
        await asyncio.sleep(0.02)
        resumed = await http.post("/agentlink/events", json={"session": "s1", "after": 2})
        if resumed.headers["Content-Type"].startswith("text/event-stream"):
            break
    rest = await read_until(resumed, "done")
    assert [(e["seq"], e["type"]) for e in rest] == [(3, "text"), (4, "done")]
    assert rest[0]["text"] == "Finished while you were away."
    caught_up = await http.post("/agentlink/events", json={"session": "s1", "after": 4})
    assert (await caught_up.json()) == {"active": False}


async def test_replayed_browser_tool_calls_are_marked_answered(http):
    await configure(http)
    http.providers.append(Recording(Reply("", [{"id": "c1", "name": "read_canvas", "arguments": {}}]), Reply("It has a sampler.", [])))
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "what is open?"})
    live = await read_until(response, "tool_call")
    assert "answered" not in live[0]
    await http.post("/agentlink/page_result", json={"session": "s1", "id": "c1", "result": {"nodes": []}})
    await read_until(response, "done")
    replay = await read_until(await http.post("/agentlink/events", json={"session": "s1", "after": 0}), "done")
    assert replay[0]["type"] == "tool_call" and replay[0]["answered"] is True


async def test_events_for_an_unknown_chat_report_nothing_to_resume(http):
    response = await http.post("/agentlink/events", json={"session": "nope", "after": 0})
    assert (await response.json()) == {"active": False}


async def test_a_phone_that_drops_before_the_first_event_can_still_resume(http):
    await configure(http)
    provider = GatedProvider(Reply("thinking done", []))
    provider.calls = 1  # gate the very first model call
    http.providers.append(provider)
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "hi"})
    response.close()
    resumed = await http.post("/agentlink/events", json={"session": "s1", "after": 0})
    assert resumed.headers["Content-Type"].startswith("text/event-stream")
    provider.gate.set()
    events = await read_until(resumed, "done")
    assert [e["type"] for e in events] == ["text", "done"]


async def test_a_second_open_stream_never_runs_a_browser_tool_the_first_one_owns(http):
    await configure(http)
    http.providers.append(Recording(Reply("", [{"id": "c1", "name": "run_canvas", "arguments": {}}]), Reply("Queued.", [])))
    first = await http.post("/agentlink/chat", json={"session": "s1", "text": "draw"})
    live = await read_until(first, "tool_call")
    assert "answered" not in live[0]
    second = await http.post("/agentlink/events", json={"session": "s1", "after": 0})
    duplicate = await read_until(second, "tool_call")
    assert duplicate[0]["answered"] is True
    first.close()  # the owner leaves without answering: the next stream may take the call over
    await asyncio.sleep(0.05)
    third = await http.post("/agentlink/events", json={"session": "s1", "after": 0})
    takeover = await read_until(third, "tool_call")
    assert "answered" not in takeover[0]
    await http.post("/agentlink/page_result", json={"session": "s1", "id": "c1", "result": {"queued": 1}})
    assert [e["type"] for e in await read_until(third, "done")][-1] == "done"


async def test_page_calls_with_unreadable_arguments_are_never_run_by_the_page(http):
    await configure(http)
    http.providers.append(Recording(Reply("", [{"id": "c1", "name": "run_canvas", "arguments": None, "raw_arguments": "{bad"}]), Reply("Sorry.", [])))
    response = await http.post("/agentlink/chat", json={"session": "s1", "text": "draw"})
    events = await read_until(response, "done")
    assert events[0]["type"] == "tool_call" and events[0]["answered"] is True


async def test_reset_does_not_resurrect_history_already_being_written(http, store, monkeypatch):
    import threading
    from agentlink.history import HistoryStore
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    save = HistoryStore.save
    def delayed_save(self, session, history):
        started.set()
        try:
            assert release.wait(5)
            save(self, session, history)
        finally:
            finished.set()
    monkeypatch.setattr(HistoryStore, 'save', delayed_save)
    await configure(http)
    session = 'abcdef0123456789'
    http.providers.append(Recording(Reply('finished', [])))
    response = await http.post('/agentlink/chat', json={'session': session, 'text': 'hello'})
    await read_until(response, 'done')
    assert await asyncio.to_thread(started.wait, 2)
    reset = asyncio.create_task(http.post('/agentlink/reset', json={'session': session}))
    try:
        await asyncio.sleep(.05)  # let the reset reach its handler while disk I/O is held
    finally:
        release.set()
    assert (await reset).status == 200
    assert await asyncio.to_thread(finished.wait, 2)
    assert not (store.path.parent / 'sessions' / (session + '.json')).exists()
