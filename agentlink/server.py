"""HTTP routes AgentLink adds to ComfyUI: the chat sidebar's API and an MCP endpoint for outside agents."""
import asyncio
import functools
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .agent import CHAT_INSTRUCTIONS, NSFW_INSTRUCTIONS, Agent
from .llm import LLMError, make_provider
from .errors import ToolError
from .characters import CharacterStore
from .tools import INSTRUCTIONS, PAGE_TOOL_NAMES, PAGE_TOOLS, Toolset

VERSION = "0.2.0"
MCP_PATH = "/agentlink/mcp"
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}
FORMATS = {"openai", "anthropic"}
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGES = 4
MAX_IMAGE_CHARS = 8 * 2**20

# How long a browser tool may take; run_canvas returns as soon as the jobs are queued.
PAGE_TIMEOUT = 120
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
    def __init__(self, client, store, provider_factory=make_provider, characters=None):
        self.store = store
        self.provider_factory = provider_factory
        self.characters = characters
        if self.characters is None and getattr(store, "path", None) is not None:
            self.characters = CharacterStore(Path(store.path).with_name("characters.json"))
        self.mcp_tools = Toolset(client, characters=self.characters)
        self.chat_tools = Toolset(client, chat=True, characters=self.characters)
        self.sessions = {}
        self._provider = None
        self._provider_config = None
        self._provider_users = 0
        self._closing = {}

    def add_routes(self, routes):
        routes.get("/agentlink/info")(self.info)
        routes.get("/agentlink/config")(self.get_config)
        routes.post("/agentlink/config")(self.set_config)
        routes.post("/agentlink/test")(self.test_connection)
        routes.post("/agentlink/chat")(self.chat)
        routes.post("/agentlink/stop")(self.stop)
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
        return web.json_response({"version": VERSION, "mcp_path": MCP_PATH, "local": is_local_request(request) is None})

    @local_only
    async def get_config(self, request):
        return web.json_response(public_config(self.store.load()))

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

    @local_only
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
        session = self.sessions.setdefault(session_id, {"history": [], "stop": asyncio.Event(), "busy": False, "pending": {}})
        if session["busy"]:
            return web.json_response({"error": "This chat is still answering. Stop it or wait."}, status=409)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)

        async def send(event):
            if event["type"] == "tool_call" and event["name"] in PAGE_TOOL_NAMES:
                # Ready before the page hears of the call, so its answer can never arrive first.
                session["pending"].setdefault(event["id"], asyncio.get_running_loop().create_future())
            await response.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))

        config = self.store.load()
        missing = self._missing_settings(config)
        if missing:
            await send({"type": "error", "message": missing})
            await send({"type": "done", "stopped": False})
            return response
        session["busy"] = True
        session["stop"].clear()
        provider = None
        try:
            provider = await self._get_provider(config)
            agent = Agent(provider, self.chat_tools, nsfw=config.get("nsfw", False), page_tools=PAGE_TOOLS,
                          page_call=functools.partial(self._ask_page, session))
            note = canvas_note(body.get("canvas")) + reference_note(image_names, len(images), config.get("vision", True))
            stream = agent.run(session["history"], text + note, session["stop"], images=images)
            try:
                async for event in stream:
                    await send(event)
            finally:
                await stream.aclose()
        except ConnectionResetError:
            session["stop"].set()
        finally:
            session["busy"] = False
            if provider is not None:
                await self._release_provider(provider)
        return response

    async def _ask_page(self, session, call):
        future = session["pending"].setdefault(call["id"], asyncio.get_running_loop().create_future())
        try:
            return await asyncio.wait_for(future, PAGE_TIMEOUT)
        except asyncio.TimeoutError:
            raise ToolError("The ComfyUI page did not answer. The user must keep the ComfyUI page open.") from None
        finally:
            session["pending"].pop(call["id"], None)

    @local_only
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

    @local_only
    async def stop(self, request):
        session = self.sessions.get(str((await request.json()).get("session")))
        if session:
            session["stop"].set()
        return web.json_response({"stopping": bool(session)})

    @local_only
    async def reset(self, request):
        session = self.sessions.pop(str((await request.json()).get("session")), None)
        if session:
            session["stop"].set()
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
