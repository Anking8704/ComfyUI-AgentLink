import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agentlink.history import HistoryStore, trimmed
from agentlink.llm import Reply
from agentlink.server import AgentLinkServer, ConfigStore


class Remembering:
    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    async def complete(self, system, messages, tools):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)

    async def close(self):
        pass


async def start(client, store, provider):
    server = AgentLinkServer(client, store, provider_factory=lambda config: provider)
    routes = web.RouteTableDef()
    server.add_routes(routes)
    app = web.Application()
    app.add_routes(routes)
    http = TestClient(TestServer(app))
    await http.start_server()
    return http


async def test_a_conversation_survives_a_restart_without_its_images(client, tmp_path):
    store = ConfigStore(tmp_path / "agentlink" / "config.json")
    store.save({"format": "openai", "base_url": "u", "model": "m", "api_key": "k", "vision": True, "nsfw": False})
    first = Remembering(Reply("A cat on a beach, got it.", []))
    http = await start(client, store, first)
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    await (await http.post("/agentlink/chat", json={"session": "abcdef0123456789", "text": "remember: cat on a beach",
                                                   "images": [{"data": png, "mime": "image/png", "name": "ref.png"}]})).text()
    record = tmp_path / "agentlink" / "sessions" / "abcdef0123456789.json"
    for _ in range(100):  # saved off the event loop, right after the reply ends
        if record.exists():
            break
        await asyncio.sleep(0.02)
    await http.close()
    saved = record.read_text(encoding="utf-8")
    assert "cat on a beach" in saved and png not in saved
    second = Remembering(Reply("You asked for a cat on a beach.", []))
    http = await start(client, store, second)  # a fresh server, as after restarting ComfyUI
    await (await http.post("/agentlink/chat", json={"session": "abcdef0123456789", "text": "what did I ask?"})).text()
    earlier = [m.get("text", "") for m in second.seen[0]]
    assert any("cat on a beach" in t for t in earlier) and any("A cat on a beach, got it." in t for t in earlier)
    await http.post("/agentlink/reset", json={"session": "abcdef0123456789"})
    assert not (tmp_path / "agentlink" / "sessions" / "abcdef0123456789.json").exists()
    await http.close()


def test_trimming_starts_at_a_user_message_so_tool_results_keep_their_calls():
    history = []
    for i in range(10):
        history += [{"role": "user", "text": str(i)}, {"role": "assistant", "text": "", "tool_calls": [{"id": f"c{i}"}]},
                    {"role": "tool", "id": f"c{i}", "content": []}, {"role": "assistant", "text": "ok"}]
    kept = trimmed(history, limit=10)
    assert kept[0]["role"] == "user" and len(kept) <= 10


def test_session_ids_cannot_name_other_files(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.save("../../evil", [{"role": "user", "text": "x"}])
    assert list(tmp_path.iterdir()) == []
    assert store.load("../../evil") == []


async def test_resetting_a_running_chat_does_not_bring_its_record_back(client, tmp_path):
    store = ConfigStore(tmp_path / "agentlink" / "config.json")
    store.save({"format": "openai", "base_url": "u", "model": "m", "api_key": "k", "vision": True, "nsfw": False})
    gate = asyncio.Event()

    class Slow(Remembering):
        async def complete(self, system, messages, tools):
            await gate.wait()
            return await super().complete(system, messages, tools)

    http = await start(client, store, Slow(Reply("late", [])))
    response = await http.post("/agentlink/chat", json={"session": "abcdef0123456789", "text": "hi"})
    await http.post("/agentlink/reset", json={"session": "abcdef0123456789"})
    gate.set()
    await response.text()
    await asyncio.sleep(0.2)
    assert not (tmp_path / "agentlink" / "sessions" / "abcdef0123456789.json").exists()
    await http.close()


def test_a_single_very_long_turn_is_kept_rather_than_dropped():
    history = [{"role": "user", "text": "go"}] + [{"role": "assistant", "text": str(i)} for i in range(200)]
    kept = trimmed(history, limit=10)
    assert kept and kept[0]["text"] == "go"
