import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agentlink.lan import LanAccess
from agentlink.llm import Reply
from agentlink.server import AgentLinkServer, ConfigStore

from test_server import ScriptedProvider


@pytest.fixture
def lan(tmp_path):
    return LanAccess(tmp_path / "agentlink" / "lan.json")


def test_off_by_default(lan):
    assert lan.view()["enabled"] is False
    assert lan.pair("000000") is None


def test_a_code_pairs_one_phone_once(lan):
    code = lan.set_enabled(True)["code"]
    token = lan.pair(code)
    assert token and lan.is_paired(token)
    assert lan.pair(code) is None
    assert lan.view()["devices"] == 1


def test_wrong_guesses_burn_the_code(lan):
    code = lan.set_enabled(True)["code"]
    wrong = "111111" if code != "111111" else "222222"
    for _ in range(LanAccess.MAX_TRIES):
        assert lan.pair(wrong) is None
    assert lan.pair(code) is None
    assert lan.view()["code"] is None


def test_codes_expire(lan, monkeypatch):
    code = lan.set_enabled(True)["code"]
    later = time.monotonic() + LanAccess.CODE_SECONDS + 1
    monkeypatch.setattr("agentlink.lan.time.monotonic", lambda: later)
    assert lan.pair(code) is None


def test_turning_it_off_shuts_paired_phones_out(lan):
    token = lan.pair(lan.set_enabled(True)["code"])
    lan.set_enabled(False)
    assert not lan.is_paired(token)
    lan.set_enabled(True)
    assert lan.is_paired(token)


def test_revoking_signs_every_phone_out(lan):
    token = lan.pair(lan.set_enabled(True)["code"])
    lan.revoke_all()
    assert not lan.is_paired(token)


def test_tokens_are_not_stored_in_the_clear(lan, tmp_path):
    token = lan.pair(lan.set_enabled(True)["code"])
    assert token not in (tmp_path / "agentlink" / "lan.json").read_text(encoding="utf-8")


def test_settings_survive_a_restart(lan, tmp_path):
    token = lan.pair(lan.set_enabled(True)["code"])
    again = LanAccess(tmp_path / "agentlink" / "lan.json")
    assert again.is_paired(token) and again.view()["enabled"] is True


async def make_client(server, remote):
    @web.middleware
    async def from_address(request, handler):
        return await handler(request.clone(remote=remote))

    routes = web.RouteTableDef()
    server.add_routes(routes)
    app = web.Application(middlewares=[from_address])
    app.add_routes(routes)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.fixture
async def setup(client, tmp_path):
    store = ConfigStore(tmp_path / "agentlink" / "config.json")
    store.save({"format": "openai", "base_url": "u", "model": "m", "api_key": "sk-secret-key-1234", "vision": True, "nsfw": False})
    providers = []
    server = AgentLinkServer(client, store, provider_factory=lambda config: providers.pop(0))
    desk = await make_client(server, "127.0.0.1")
    phone = await make_client(server, "10.200.42.50")
    yield server, desk, phone, providers
    await desk.close()
    await phone.close()


async def chat(client, text="hi"):
    return await client.post("/agentlink/chat", json={"session": "p1", "text": text})


async def test_unpaired_phone_is_refused_with_a_pointer_to_the_setting(setup):
    _, _, phone, _ = setup
    response = await chat(phone)
    assert response.status == 403
    assert "pair" in (await response.json())["error"].lower()


async def test_paired_phone_can_chat(setup):
    server, desk, phone, providers = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    paired = await phone.post("/agentlink/pair", json={"code": code})
    assert paired.status == 200
    providers.append(ScriptedProvider(Reply("hello phone", [])))
    response = await chat(phone)
    assert response.status == 200 and "hello phone" in await response.text()
    info = await (await phone.get("/agentlink/info")).json()
    assert info["local"] is False and info["paired"] is True


async def test_wrong_code_is_refused(setup):
    _, desk, phone, _ = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    response = await phone.post("/agentlink/pair", json={"code": "999999" if code != "999999" else "888888"})
    assert response.status == 403


async def test_paired_phone_sees_the_model_but_never_the_key_and_cannot_change_settings(setup):
    _, desk, phone, _ = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    await phone.post("/agentlink/pair", json={"code": code})
    config = await (await phone.get("/agentlink/config")).json()
    assert config["model"] == "m" and "sk-" not in str(config) and "1234" not in str(config)
    assert (await phone.post("/agentlink/config", json={"format": "openai", "base_url": "x", "model": "y"})).status == 403
    assert (await phone.post("/agentlink/lan", json={"enabled": False})).status == 403
    assert (await phone.get("/agentlink/lan")).status == 403
    assert (await phone.post("/agentlink/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})).status == 403


async def test_pairing_is_refused_while_phone_access_is_off(setup):
    _, _, phone, _ = setup
    assert (await phone.post("/agentlink/pair", json={"code": "123456"})).status == 403


async def test_paired_phone_requests_from_another_site_are_refused(setup):
    _, desk, phone, _ = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    await phone.post("/agentlink/pair", json={"code": code})
    response = await phone.post("/agentlink/chat", json={"session": "p1", "text": "hi"}, headers={"Origin": "http://evil.example"})
    assert response.status == 403


async def test_desktop_sees_code_addresses_and_device_count(setup):
    _, desk, phone, _ = setup
    view = await (await desk.post("/agentlink/lan", json={"enabled": True})).json()
    assert len(view["code"]) == 6 and view["expires_in"] > 0 and isinstance(view["addresses"], list)
    await phone.post("/agentlink/pair", json={"code": view["code"]})
    view = await (await desk.get("/agentlink/lan")).json()
    assert view["devices"] == 1 and view["code"] is None
    view = await (await desk.post("/agentlink/lan", json={"revoke": True})).json()
    assert view["devices"] == 0


async def test_scanning_the_pairing_link_pairs_the_phone_and_opens_agentlink(setup):
    server, desk, phone, providers = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    response = await phone.get(f"/agentlink/pair?code={code}&next=%2F%3Fagentlink%3Dopen", allow_redirects=False)
    assert response.status == 302 and response.headers["Location"] == "/?agentlink=open"
    assert "agentlink_device=" in response.headers["Set-Cookie"] and "HttpOnly" in response.headers["Set-Cookie"]
    phone.session.cookie_jar.update_cookies(response.cookies)
    info = await (await phone.get("/agentlink/info")).json()
    assert info["paired"] is True
    again = await phone.get(f"/agentlink/pair?code={code}", allow_redirects=False)
    assert again.status == 403 and "配对" in await again.text()


async def test_pairing_link_never_redirects_off_site(setup):
    _, desk, phone, _ = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    response = await phone.get(f"/agentlink/pair?code={code}&next=//evil.example/x", allow_redirects=False)
    assert response.status == 302 and response.headers["Location"] == "/"


async def test_pairing_link_rejects_redirects_hidden_with_control_characters(setup):
    _, desk, phone, _ = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    for target in ["/%09/evil.example", "/%5C%5Cevil.example", "https://evil.example", "/%0D%0A//evil.example"]:
        response = await desk.get(f"/agentlink/pair?code={code}&next={target}", allow_redirects=False)
        assert response.status == 302 and response.headers["Location"] == "/", target


async def test_a_non_ascii_pairing_code_is_refused_not_a_server_error(setup):
    _, desk, phone, _ = setup
    await desk.post("/agentlink/lan", json={"enabled": True})
    response = await phone.get("/agentlink/pair?code=%E4%B8%AD%E6%96%87", allow_redirects=False)
    assert response.status == 403


async def test_status_tells_a_paired_phone_whether_the_chat_is_still_working(setup):
    server, desk, phone, providers = setup
    code = (await (await desk.post("/agentlink/lan", json={"enabled": True})).json())["code"]
    await phone.post("/agentlink/pair", json={"code": code})
    assert await (await phone.post("/agentlink/status", json={"session": "unknown"})).json() == {"busy": False, "reply": ""}
    providers.append(ScriptedProvider(Reply("画好了，一只海边的猫。", [])))
    await (await chat(phone)).text()
    assert await (await phone.post("/agentlink/status", json={"session": "p1"})).json() == {"busy": False, "reply": "画好了，一只海边的猫。"}


async def test_status_is_refused_to_unpaired_devices(setup):
    _, _, phone, _ = setup
    assert (await phone.post("/agentlink/status", json={"session": "p1"})).status == 403
