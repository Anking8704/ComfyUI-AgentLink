"""HTTP routes AgentLink adds to ComfyUI: the chat sidebar's API and an MCP endpoint for outside agents."""
import asyncio
import functools
import itertools
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .agent import CHAT_INSTRUCTIONS, NSFW_INSTRUCTIONS, Agent
from .llm import LLMError, make_provider
from .errors import ToolError
from .characters import CharacterStore
from .history import HistoryStore
from .lan import LanAccess
from .tools import INSTRUCTIONS, PAGE_TOOL_NAMES, PAGE_TOOLS, Toolset

VERSION = "0.3.2"
MCP_PATH = "/agentlink/mcp"
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}
FORMATS = {"openai", "anthropic"}
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGES = 4
MAX_IMAGE_CHARS = 8 * 2**20

# How long a browser tool may take; run_canvas returns as soon as the jobs are queued.
PAGE_TIMEOUT = 120
PAIR_FAILED_PAGE = (
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
    "<body style='font-family:sans-serif;padding:24px;line-height:1.6'><h2>配对没有成功 · Pairing failed</h2>"
    "<p>配对码不对、已经用过或已过期（10 分钟），或者电脑上关闭了手机访问。请在电脑的 AgentLink 设置 → 手机访问里点“换一个配对码”，再扫一次。</p>"
    "<p>The code is wrong, used or expired (10 minutes), or phone access is off. On the computer, open AgentLink settings → "
    "Phone access, get a new code and scan again.</p>")
KEEPALIVE = 15
MAX_SESSIONS = 60
# Where a pairing link may send the phone afterwards: a path on this server, nothing that a browser could read as another site.
SAFE_NEXT = re.compile(r"/(?![/\\])[A-Za-z0-9/_\-.~?=&%]*")
DEFAULT_CONFIG = {"format": "openai", "base_url": "", "model": "", "api_key": "", "vision": True, "nsfw": False}


def is_local_request(request):
    """Why the request is refused, or None. The API key and the GPU belong to whoever sits at this computer."""
    if (request.remote or "") not in LOOPBACK:
        return "AgentLink only accepts requests from this computer. Open ComfyUI at http://127.0.0.1 to use it."
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).hostname not in LOOPBACK:
        return "Requests from other web pages are not allowed."
    # A JSON body forces browsers to ask first, so a web page cannot quietly post here.
    if request.method == "POST" and request.content_type != "application/json":
        return "Requests must be JSON (Content-Type: application/json)."
    return None


def local_only(handler):
    @functools.wraps(handler)
    async def guarded(self, request):
        reason = is_local_request(request)
        if reason:
            return web.json_response({"error": reason}, status=403)
        return await handler(self, request)
    return guarded


def _same_site(request):
    """Why a phone's request is refused on page grounds, or None: it must come from ComfyUI's own page and be JSON."""
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return "Requests from other web pages are not allowed."
    if request.method == "POST" and request.content_type != "application/json":
        return "Requests must be JSON (Content-Type: application/json)."
    return None


def local_or_paired(handler):
    """For the chat itself: this computer, or a phone paired under phone access. Settings stay local_only."""
    @functools.wraps(handler)
    async def guarded(self, request):
        if (request.remote or "") in LOOPBACK:
            reason = is_local_request(request)
        elif not self.lan.is_paired(request.cookies.get(LanAccess.COOKIE)):
            reason = "This device is not paired. On the computer, turn on phone access in the AgentLink settings and enter the pairing code here."
        else:
            reason = _same_site(request)
        if reason:
            return web.json_response({"error": reason}, status=403)
        return await handler(self, request)
    return guarded


class ConfigStore:
    """Model settings, kept outside ComfyUI's per-user folders so the userdata API never serves the key."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except (OSError, ValueError):
            return dict(DEFAULT_CONFIG)

    def save(self, config):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


def public_config(config):
    key = config["api_key"]
    view = {k: v for k, v in config.items() if k != "api_key"}
    view["has_key"] = bool(key)
    view["key_hint"] = f"{key[:3]}…{key[-4:]}" if len(key) >= 8 else ("…" if key else "")
    return view


def canvas_note(canvas):
    """A line telling the model what the user has open, so it starts from that workflow."""
    if not isinstance(canvas, dict):
        return ""
    if not canvas.get("nodes"):
        return "\n\n[The ComfyUI canvas is empty.]"
    types = ", ".join(str(t) for t in (canvas.get("types") or [])[:15])
    return f"\n\n[Open on the ComfyUI canvas: \"{str(canvas.get('name') or 'untitled')[:120]}\", {canvas['nodes']} nodes ({types}). Use read_canvas for ids and values.]"


def reference_images(raw):
    """The attached images as the model receives them, and their names in ComfyUI's input folder. None if malformed."""
    if not isinstance(raw, list) or len(raw) > MAX_IMAGES:
        return None
    images, names = [], []
    for item in raw:
        if not isinstance(item, dict) or item.get("mime") not in IMAGE_TYPES or not isinstance(item.get("data"), str) or len(item["data"]) > MAX_IMAGE_CHARS:
            return None
        images.append({"data": item["data"], "mime": item["mime"]})
        if item.get("name"):
            names.append(str(item["name"]))
    return images, names


def reference_note(names, count, vision):
    if not count:
        return ""
    note = f"\n\n[The user attached {count} reference image(s)."
    if names:
        note += f" They are in ComfyUI's input folder as: {', '.join(names)}. To use one in the workflow, set a LoadImage node's image input to that name with edit_canvas."
    if not vision:
        note += " This model cannot see them; call describe_image with the file name to get their tags."
    return note + "]"


def _mcp_content(block):
    if block["type"] == "image":
        return {"type": "image", "data": block["data"], "mimeType": block["mime"]}
    return block


class AgentLinkServer:
    def __init__(self, client, store, provider_factory=make_provider, characters=None, lan=None, histories=None):
        self.store = store
        if histories is None and getattr(store, "path", None) is not None:
            histories = HistoryStore(str(Path(store.path).with_name("sessions")))
        self.histories = histories
        if lan is None and getattr(store, "path", None) is not None:
            lan = LanAccess(Path(store.path).with_name("lan.json"))
        self.lan = lan
        self.provider_factory = provider_factory
        self.characters = characters
        if self.characters is None and getattr(store, "path", None) is not None:
            self.characters = CharacterStore(Path(store.path).with_name("characters.json"))
        self.mcp_tools = Toolset(client, characters=self.characters)
        self.chat_tools = Toolset(client, chat=True, characters=self.characters)
        self.sessions = {}
        self._stream_ids = itertools.count(1)
        self._provider = None
        self._provider_config = None
        self._provider_users = 0
        self._closing = {}

    def add_routes(self, routes):
        routes.get("/agentlink/info")(self.info)
        routes.get("/agentlink/lan")(self.get_lan)
        routes.post("/agentlink/lan")(self.set_lan)
        routes.post("/agentlink/pair")(self.pair)
        routes.get("/agentlink/pair")(self.pair_link)
        routes.get("/agentlink/config")(self.get_config)
        routes.post("/agentlink/config")(self.set_config)
        routes.post("/agentlink/test")(self.test_connection)
        routes.post("/agentlink/chat")(self.chat)
        routes.post("/agentlink/events")(self.events)
        routes.post("/agentlink/stop")(self.stop)
        routes.post("/agentlink/status")(self.status)
        routes.post("/agentlink/reset")(self.reset)
        routes.post("/agentlink/page_result")(self.page_result)
        routes.post(MCP_PATH)(self.mcp)
        routes.get(MCP_PATH)(self.mcp_no_stream)

    async def _get_provider(self, config):
        idle = None
        if config != self._provider_config:
            replacement = self.provider_factory(config)
            if self._provider is not None:
                if self._provider_users:
                    self._closing[self._provider] = self._provider_users
                else:
                    idle = self._provider
            self._provider, self._provider_config = replacement, dict(config)
            self._provider_users = 0
        provider = self._provider
        self._provider_users += 1
        # Publish the replacement and its lease before yielding to close().
        if idle is not None:
            await idle.close()
        return provider

    async def _release_provider(self, provider):
        if provider is self._provider:
            self._provider_users -= 1
        elif provider in self._closing:
            self._closing[provider] -= 1
            if self._closing[provider] == 0:
                del self._closing[provider]
                await provider.close()

    def _missing_settings(self, config):
        if not config["base_url"] or not config["model"]:
            return "Set the API address and model in the AgentLink settings first."
        return None

    async def info(self, request):
        local = is_local_request(request) is None
        paired = not local and self.lan.is_paired(request.cookies.get(LanAccess.COOKIE))
        return web.json_response({"version": VERSION, "mcp_path": MCP_PATH, "local": local, "paired": paired,
                                  "lan": self.lan.view()["enabled"]})

    @local_only
    async def get_lan(self, request):
        return web.json_response(self.lan.view())

    @local_only
    async def set_lan(self, request):
        body = await request.json()
        if "enabled" in body:
            view = self.lan.set_enabled(bool(body["enabled"]))
        elif body.get("revoke"):
            view = self.lan.revoke_all()
        elif body.get("new_code"):
            view = self.lan.new_code()
        else:
            view = self.lan.view()
        return web.json_response(view)

    async def pair(self, request):
        reason = _same_site(request)
        if reason:
            return web.json_response({"error": reason}, status=403)
        token = self.lan.pair((await request.json()).get("code", ""))
        if token is None:
            return web.json_response({"error": "Wrong or expired pairing code, or phone access is off. Get a new code on the computer."}, status=403)
        response = web.json_response({"paired": True})
        response.set_cookie(LanAccess.COOKIE, token, max_age=365 * 24 * 3600, httponly=True, samesite="Strict", path="/agentlink")
        return response

    async def pair_link(self, request):
        """The link in the pairing QR code: a phone camera opens it, the code pairs the phone, and AgentLink opens."""
        target = request.query.get("next", "/")
        if not SAFE_NEXT.fullmatch(target):
            target = "/"
        if is_local_request(request) is None:
            raise web.HTTPFound(target)
        token = self.lan.pair(request.query.get("code", ""))
        if token is None:
            return web.Response(status=403, content_type="text/html", charset="utf-8", text=PAIR_FAILED_PAGE)
        response = web.HTTPFound(target)
        response.set_cookie(LanAccess.COOKIE, token, max_age=365 * 24 * 3600, httponly=True, samesite="Lax", path="/agentlink")
        raise response

    @local_or_paired
    async def get_config(self, request):
        view = public_config(self.store.load())
        if (request.remote or "") not in LOOPBACK:
            # A phone only needs to know which model answers; not even a hint of the key.
            view.pop("key_hint")
        return web.json_response(view)

    @local_only
    async def set_config(self, request):
        body = await request.json()
        if body.get("format") not in FORMATS:
            return web.json_response({"error": f"format must be one of {sorted(FORMATS)}"}, status=400)
        config = self.store.load()
        new_url = str(body.get("base_url", "")).strip()
        old_origin = urlsplit(config["base_url"])
        new_origin = urlsplit(new_url)
        if (old_origin.scheme, old_origin.netloc, config["format"]) != (new_origin.scheme, new_origin.netloc, body["format"]):
            config["api_key"] = ""
        config.update(format=body["format"], base_url=str(body.get("base_url", "")).strip(),
                      model=str(body.get("model", "")).strip(), vision=bool(body.get("vision", True)),
                      nsfw=bool(body.get("nsfw", False)))
        if body.get("api_key"):
            config["api_key"] = str(body["api_key"]).strip()
        if body.get("clear_key"):
            config["api_key"] = ""
        self.store.save(config)
        return web.json_response(public_config(config))

    @local_only
    async def test_connection(self, request):
        config = self.store.load()
        missing = self._missing_settings(config)
        if missing:
            return web.json_response({"ok": False, "error": missing})
        provider = None
        try:
            provider = await self._get_provider(config)
            instructions = CHAT_INSTRUCTIONS + (NSFW_INSTRUCTIONS if config.get("nsfw") else "")
            reply = await provider.complete(instructions, [{"role": "user", "text": "ping"}], [])
        except LLMError as e:
            return web.json_response({"ok": False, "error": str(e)})
        finally:
            if provider is not None:
                await self._release_provider(provider)
        return web.json_response({"ok": True, "reply": reply.text[:200]})

    @local_or_paired
    async def chat(self, request):
        body = await request.json()
        session_id, text = str(body.get("session") or ""), str(body.get("text") or "").strip()
        attached = reference_images(body.get("images") or [])
        if attached is None:
            return web.json_response({"error": f"images must be up to {MAX_IMAGES} PNG, JPEG or WebP images"}, status=400)
        images, image_names = attached
        if not session_id or not (text or images):
            return web.json_response({"error": "session and text are required"}, status=400)
        text = text or "(reference image)"
        session = self._session(session_id)
        if session["busy"]:
            return web.json_response({"error": "This chat is still answering. Stop it or wait."}, status=409)
        config = self.store.load()
        session["events"], session["done"], session["owners"] = [], False, {}
        missing = self._missing_settings(config)
        if missing:
            self._emit(session, {"type": "error", "message": missing})
            self._emit(session, {"type": "done", "stopped": False})
            session["done"] = True
            return await self._stream(request, session, 0)
        session["busy"] = True
        session["stop"].clear()
        note = canvas_note(body.get("canvas")) + reference_note(image_names, len(images), config.get("vision", True))
        # The turn runs on its own: a phone that locks its screen or loses Wi-Fi for a moment can reattach and catch up
        # through /agentlink/events instead of the work stopping with the connection.
        session["task"] = asyncio.get_running_loop().create_task(self._run_turn(session, config, text + note, images))
        return await self._stream(request, session, 0)

    def _session(self, session_id):
        if session_id not in self.sessions:
            # After a restart the page still shows this chat; its saved history lets the model remember it too.
            history = self.histories.load(session_id) if self.histories else []
            idle = [k for k, v in self.sessions.items() if not v["busy"]]
            for old in idle[:max(0, len(self.sessions) - MAX_SESSIONS + 1)]:
                del self.sessions[old]  # the oldest idle chats; their history is on disk
            self.sessions[session_id] = {"id": session_id, "history": history, "stop": asyncio.Event(), "busy": False, "pending": {},
                                         "events": [], "done": True, "changed": asyncio.Event(), "task": None, "owners": {}}
        return self.sessions[session_id]

    def _emit(self, session, event):
        if event["type"] == "tool_call" and event["name"] in PAGE_TOOL_NAMES and event.get("arguments") is not None:
            # Ready before the page hears of the call, so its answer can never arrive first. Calls with unreadable
            # arguments are refused by the agent itself, so the page must not run them.
            session["pending"].setdefault(event["id"], asyncio.get_running_loop().create_future())
        session["events"].append(event)
        changed, session["changed"] = session["changed"], asyncio.Event()
        changed.set()

    async def _run_turn(self, session, config, text, images):
        provider = None
        try:
            provider = await self._get_provider(config)
            agent = Agent(provider, self.chat_tools, nsfw=config.get("nsfw", False), page_tools=PAGE_TOOLS,
                          page_call=functools.partial(self._ask_page, session))
            stream = agent.run(session["history"], text, session["stop"], images=images)
            try:
                async for event in stream:
                    self._emit(session, event)
            finally:
                await stream.aclose()
        except Exception as e:  # noqa: BLE001 - the page must hear about any failure, then the turn ends
            self._emit(session, {"type": "error", "message": f"{type(e).__name__}: {e}"})
            self._emit(session, {"type": "done", "stopped": False})
        finally:
            session["busy"] = False
            session["done"] = True
            changed, session["changed"] = session["changed"], asyncio.Event()
            changed.set()
            try:
                if provider is not None:
                    await self._release_provider(provider)
            finally:
                # A chat that was reset (or replaced) meanwhile must not be written back.
                if self.histories and self.sessions.get(session["id"]) is session:
                    snapshot = list(session["history"])
                    await asyncio.get_running_loop().run_in_executor(None, self.histories.save, session["id"], snapshot)

    def _wire(self, session, event, seq, stream_id):
        payload = dict(event, seq=seq)
        if event["type"] == "tool_call" and event["name"] in PAGE_TOOL_NAMES:
            future = session["pending"].get(event["id"])
            owner = session["owners"].setdefault(event["id"], stream_id)
            if future is None or future.done() or owner != stream_id:
                # Answered already (before a dropped connection), or another open stream is running it: never run it twice.
                payload["answered"] = True
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    async def _stream(self, request, session, after):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        seq = max(0, int(after))
        # This stream follows one turn; when a new turn replaces the event list, it stops instead of mixing them.
        events, stream_id = session["events"], next(self._stream_ids)
        try:
            while True:
                changed = session["changed"]
                while seq < len(events):
                    event = events[seq]
                    seq += 1
                    await response.write(self._wire(session, event, seq, stream_id))
                if session["done"] or session["events"] is not events:
                    break
                try:
                    await asyncio.wait_for(changed.wait(), KEEPALIVE)
                except asyncio.TimeoutError:
                    await response.write(b": keepalive\n\n")
        except (ConnectionResetError, ConnectionError):
            pass  # The page left; the turn keeps running and can be picked up again.
        finally:
            # Calls this stream delivered but nobody answered yet may be taken over by the next stream that attaches.
            for call_id, owner in list(session["owners"].items()):
                future = session["pending"].get(call_id)
                if owner == stream_id and future is not None and not future.done():
                    del session["owners"][call_id]
        return response

    @local_or_paired
    async def events(self, request):
        """Reattach to a chat turn: replays events after `after` (their seq numbers), then follows it live."""
        body = await request.json()
        session = self.sessions.get(str(body.get("session") or ""))
        if session is None or (session["done"] and not session["events"]):
            return web.json_response({"active": False})
        try:
            after = int(body.get("after") or 0)
        except (TypeError, ValueError):
            return web.json_response({"error": "after must be a number"}, status=400)
        if session["done"] and after >= len(session["events"]):
            return web.json_response({"active": False})
        return await self._stream(request, session, after)

    async def _ask_page(self, session, call):
        future = session["pending"].setdefault(call["id"], asyncio.get_running_loop().create_future())
        try:
            return await asyncio.wait_for(future, PAGE_TIMEOUT)
        except asyncio.TimeoutError:
            raise ToolError("The ComfyUI page did not answer. The user must keep the ComfyUI page open.") from None
        finally:
            session["pending"].pop(call["id"], None)

    @local_or_paired
    async def page_result(self, request):
        body = await request.json()
        session = self.sessions.get(str(body.get("session")))
        future = session["pending"].get(str(body.get("id"))) if session else None
        if future is None or future.done():
            return web.json_response({"accepted": False})
        if body.get("error"):
            future.set_exception(ToolError(str(body["error"])))
        else:
            future.set_result(body.get("result"))
        return web.json_response({"accepted": True})

    @local_or_paired
    async def status(self, request):
        """Whether a chat is still working, and its latest reply. The phone app polls this while it is in the background."""
        session = self.sessions.get(str((await request.json()).get("session")))
        if session is None:
            return web.json_response({"busy": False, "reply": ""})
        reply = next((e["text"] for e in reversed(session["events"]) if e["type"] == "text"), "")
        return web.json_response({"busy": session["busy"], "reply": reply[:300]})

    @local_or_paired
    async def stop(self, request):
        session = self.sessions.get(str((await request.json()).get("session")))
        if session:
            session["stop"].set()
        return web.json_response({"stopping": bool(session)})

    @local_or_paired
    async def reset(self, request):
        session_id = str((await request.json()).get("session"))
        session = self.sessions.pop(session_id, None)
        if session:
            session["stop"].set()
            # A completed turn may still be saving in the disk executor. Delete only after
            # that write finishes, otherwise it can recreate the chat after reset returns.
            task = session.get("task")
            if task is not None:
                await asyncio.shield(task)
        if self.histories and session_id not in self.sessions:
            self.histories.delete(session_id)
        return web.json_response({"reset": True})

    @local_only
    async def mcp(self, request):
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        messages = body if isinstance(body, list) else [body]
        replies = [r for r in [await self._rpc(m) for m in messages] if r is not None]
        if not replies:
            return web.Response(status=202)
        return web.json_response(replies if isinstance(body, list) else replies[0])

    async def mcp_no_stream(self, request):
        return web.Response(status=405, headers={"Allow": "POST"})

    async def _rpc(self, message):
        method, msg_id, params = message.get("method"), message.get("id"), message.get("params") or {}
        if msg_id is None:
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {
                "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "comfyui-agentlink", "version": VERSION},
                "instructions": INSTRUCTIONS,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": s["name"], "description": s["description"], "inputSchema": s["input_schema"]} for s in self.mcp_tools.schemas()]}
        elif method == "tools/call":
            outcome = await self.mcp_tools.call(params.get("name"), params.get("arguments") or {})
            result = {"content": [_mcp_content(b) for b in outcome.content], "isError": outcome.is_error}
        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
