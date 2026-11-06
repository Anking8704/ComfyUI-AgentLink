"""The ComfyUI tools shared by the built-in chat agent and the MCP endpoint."""
import asyncio
import base64
import inspect
import io
import json
import logging
import time
import types
import typing
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, UnidentifiedImageError

from .client import ComfyError, ComfyOffline
from .errors import ToolError
from .ui_format import attach_prompt, display_risks, embedded_prompt, to_ui
from .validate import validate_prompt
from .workflow import WorkflowError, apply_overrides, detect_format, randomize_seeds, summarize_api

MAX_COMBO_OPTIONS = 50
# MCP clients commonly time a call out around five minutes; longer waits go through repeat calls.
MAX_WAIT_SECONDS = 240
TERMINAL_STATES = {"completed", "failed", "cancelled", "not_found"}
UPLOADABLE = {".png", ".jpg", ".jpeg", ".webp"}
API_SHAPE_NOTE = 'workflow must be an API-format graph: {"1": {"class_type": "...", "inputs": {...}}}'
EXPORT_NOTE = "UI-format workflows cannot run here. Export it in ComfyUI with Save (API Format), then run that file."

INSTRUCTIONS = """You operate the user's local ComfyUI. Typical flow: list_workflows, read_workflow to find node ids,
run_workflow with overrides, get_job with wait_seconds until finished, then get_image to look at the result.
To build a new workflow: search_nodes and get_node_schema for each node, write an API-format graph
({"1": {"class_type": ..., "inputs": {...}}}, links as ["node_id", output_index]), check it with
validate_workflow, then run_workflow(workflow=...) or save_workflow. Use list_models and search_nodes
instead of guessing names; base models may sit in checkpoints, diffusion_models or unet, so search with
list_models(query=...) rather than one folder. For named characters first search_character_loras; resolve ambiguity
by exact installed model_path, read_character, and ask for unknown triggers/base-model compatibility instead of inventing
them. save_character persists user-provided triggers/settings without another confirmation. list_characters inspects
saved records. Character tools are local-only; no downloads. trigger_words=null is unknown, [] is confirmed none;
preserve strength 0. These tools do not edit a browser canvas over MCP. Call free_memory when done so models stop
occupying RAM and VRAM."""

# Tools the ComfyUI page answers itself, because only it holds the workflow the user has open.
PAGE_TOOLS = [
    {"name": "read_canvas",
     "description": "Read the workflow open on the user's ComfyUI canvas: its name and every node with id, class_type, title, "
                    "current widget values and named sockets, including incomplete nodes, plus a target token. Start here for any request to generate or change something.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "edit_canvas",
     "description": "Set widget values on the open canvas; the user sees the change live. changes maps \"node_id.input\" to a value, "
                    "e.g. {\"6.text\": \"1girl, beach, sunset\", \"3.steps\": 25, \"5.width\": 832}. Only widgets can be set, not connections. "
                    "Option inputs (sampler, model files) must use one of the node's options; get_node_schema lists them.",
     "input_schema": {"type": "object", "properties": {"changes": {"type": "object"}, "target": {"type": "string"}}, "required": ["changes"]}},
    {"name": "run_canvas",
     "description": "Queue the open canvas workflow, like pressing Run, count times. Returns prompt_ids; wait for each with "
                    "get_job(prompt_id, wait_seconds). Seeds follow each node's control_after_generate setting. "
                    "The user sees progress and the images in the chat by themselves. count is 1–8. "
                    "Optional target from read_canvas binds generation to that graph. Stale canvases or stopped chats stop the batch; "
                    "an already queued job is reported in the error and must not be queued again blindly.",
     "input_schema": {"type": "object", "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 8}, "target": {"type": "string"}}, "required": []}},
    {"name": "patch_canvas",
     "description": "Transactionally edit the inspected root canvas in place. target comes from read_canvas or the last patch. "
                    "operations: add_node(ref, class_type, widgets?, position?[x,y], near?node_id); "
                    "remove_node(node); set_widget(node, widget, value); connect(from, output, to, input); disconnect(node, input). "
                    "Each operation has op. Node references are existing string ids or unique temporary refs from earlier add_node. "
                    "Connections use exact socket names. Replaces an existing input connection. Entire patch rolls back on failure; "
                    "stale targets fail. Does not run or open a tab.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "operations": {"type": "array", "items": {"type": "object"}}}, "required": ["target", "operations"]}},
    {"name": "undo_canvas",
     "description": "Undo the most recent AgentLink patch/edit as one unit on the inspected workflow. target from read_canvas or last mutation. "
                    "Refuses if manual changes followed the edit; read_canvas does not override this protection.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}},
]
PAGE_TOOL_NAMES = {tool["name"] for tool in PAGE_TOOLS}

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}


@dataclass
class ToolResult:
    content: list
    structured: dict | None = None
    is_error: bool = False
    event: dict | None = None

    @classmethod
    def of(cls, value, event=None):
        if isinstance(value, ToolResult):
            return value
        text = json.dumps(value, ensure_ascii=False, indent=2)
        return cls([{"type": "text", "text": text}], structured=value, event=event)

    @classmethod
    def error(cls, message):
        return cls([{"type": "text", "text": message}], is_error=True)

    @classmethod
    def image(cls, data, mime):
        return cls([{"type": "image", "data": base64.b64encode(data).decode("ascii"), "mime": mime}])


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    required: list
    run: Any = field(repr=False)

    def schema(self):
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.parameters, "required": self.required}}


def _json_type(annotation):
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        annotation = next(arg for arg in typing.get_args(annotation) if arg is not type(None))
    return {"type": JSON_TYPES[typing.get_origin(annotation) or annotation]}


def _describe(method):
    hints = typing.get_type_hints(method)
    parameters, required = {}, []
    for name, param in inspect.signature(method).parameters.items():
        parameters[name] = _json_type(hints[name])
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return Tool(method.__name__, inspect.getdoc(method), parameters, required, method)


def _gb(value):
    return round(value / 2**30, 1)


def _trim_combo(spec):
    options = spec[0] if isinstance(spec[0], list) else None
    extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if options is None and spec[0] == "COMBO":
        options = extra.get("options")
    if not options or len(options) <= MAX_COMBO_OPTIONS:
        return spec
    trimmed = {**extra, "total_options": len(options)}
    if spec[0] == "COMBO":
        return ["COMBO", {**trimmed, "options": options[:MAX_COMBO_OPTIONS]}]
    return [options[:MAX_COMBO_OPTIONS], trimmed]


def _trim_schema(schema):
    for group in schema.get("input", {}).values():
        for name, spec in group.items():
            if isinstance(spec, list) and spec:
                group[name] = _trim_combo(spec)
    return schema


def _job_summary(job):
    summary = {"prompt_id": job["id"], "status": job["status"]}
    images = []
    for node_id, output in job.get("outputs", {}).items():
        for item in output.get("images", []):
            images.append({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output"), "node_id": node_id})
    if images:
        summary["images"] = images
    if "execution_error" in job:
        error = job["execution_error"]
        summary["error"] = {key: error.get(key) for key in ("node_id", "node_type", "exception_type", "exception_message")}
    return summary


def _runnable_prompt(data):
    """The API prompt to submit for a saved file, or None for canvas files AgentLink did not write."""
    file_format = detect_format(data)
    if file_format == "api":
        return data
    if file_format == "ui":
        return embedded_prompt(data)
    return None


class Toolset:
    TOOLS = ("comfy_status", "list_models", "search_nodes", "get_node_schema", "list_workflows", "read_workflow",
             "run_workflow", "get_job", "get_image", "upload_image", "cancel_job", "validate_workflow",
             "save_workflow", "free_memory", "describe_image", "list_characters", "search_character_loras",
             "read_character", "save_character")
    # Only useful when the agent runs inside the page that can show it.
    CHAT_TOOLS = ("show_in_canvas",)

    def __init__(self, client, poll_interval=1.0, chat=False, characters=None):
        self.client = client
        self.characters = characters
        self.poll_interval = poll_interval
        self._object_info = {}
        names = self.TOOLS + (self.CHAT_TOOLS if chat else ())
        self.tools = {name: _describe(getattr(self, name)) for name in names}

    def schemas(self):
        return [tool.schema() for tool in self.tools.values()]

    async def call(self, name, arguments):
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult.error(f"Unknown tool {name!r}. Available: {', '.join(self.tools)}")
        if not isinstance(arguments, dict):
            return ToolResult.error(f"{name}: arguments must be an object, got {type(arguments).__name__}")
        missing = [p for p in tool.required if p not in arguments]
        unknown = [p for p in arguments if p not in tool.parameters]
        if missing or unknown:
            return ToolResult.error(f"{name}: missing {missing or 'nothing'}, unknown {unknown or 'nothing'}. Parameters: {', '.join(tool.parameters)}")
        try:
            return ToolResult.of(await tool.run(**arguments))
        except ToolError as e:
            return ToolResult.error(str(e))
        except Exception as e:
            logging.exception("[AgentLink] tool %s failed", name)
            return ToolResult.error(f"{name} failed unexpectedly: {type(e).__name__}: {e}")

    async def _object_info_cached(self, refresh=False):
        if refresh or not self._object_info:
            self._object_info = await self.client.get_json("/object_info")
        return self._object_info

    def _characters(self):
        if self.characters is None:
            raise ToolError("Character storage is not configured by the host")
        return self.characters

    async def list_characters(self, query: str = "", limit: int = 50) -> dict:
        """List saved local character records, optionally filtering character, alias or model filename. Unknown fields are null."""
        return {"records": self._characters().list(query, limit)}

    async def search_character_loras(self, query: str, limit: int = 50) -> dict:
        """Search saved character names/confirmed aliases and installed LoRA filenames. Exact names/aliases rank first.
        Returns exact relative model paths, saved records and explicit local sidecar metadata when available.
        Ask which candidate/version to use if ambiguous; never infer triggers from training tag frequency.
        """
        return self._characters().search(query, await self._model_files("loras"), limit)

    async def read_character(self, character: str, model_path: str = "") -> dict:
        """Read one saved character by exact name or alias. Supply exact model_path to disambiguate multiple LoRAs/versions."""
        return self._characters().read(character, model_path)

    async def save_character(self, record: dict) -> dict:
        """Save/update a user-confirmed local character and exact installed LoRA. record requires character and model_path.
        Optional: aliases (string list), trigger_words (string list; null unknown, [] confirmed none), appearance_prompt,
        strength_model/strength_clip (numbers including 0), base_model, provenance. Unknown values are null.
        Updates merge supplied fields for the exact character/model pair; lists replace previous lists. No downloads.
        Save supplied missing triggers immediately without asking a second confirmation; do not invent fields.
        """
        saved = self._characters().save(record, await self._model_files("loras"))
        return {"saved": True, "record": saved}

    async def _fetch_job(self, prompt_id):
        try:
            return _job_summary(await self.client.get_json(f"/api/jobs/{quote(prompt_id, safe='')}"))
        except ComfyError as e:
            if e.status == 404:
                return {"prompt_id": prompt_id, "status": "not_found"}
            raise

    async def comfy_status(self) -> dict:
        """Check whether ComfyUI is running, its free RAM/VRAM and how many jobs are queued."""
        try:
            stats = await self.client.get_json("/system_stats")
            queue = await self.client.get_json("/queue")
        except ComfyOffline as e:
            return {"online": False, "detail": str(e)}
        return {
            "online": True,
            "version": stats["system"].get("comfyui_version"),
            "ram_free_gb": _gb(stats["system"]["ram_free"]),
            "ram_total_gb": _gb(stats["system"]["ram_total"]),
            "devices": [{"name": d["name"], "vram_free_gb": _gb(d["vram_free"]), "vram_total_gb": _gb(d["vram_total"])} for d in stats["devices"]],
            "queue": {"running": len(queue["queue_running"]), "pending": len(queue["queue_pending"])},
        }

    async def _model_files(self, folder):
        try:
            return await self.client.get_json("/models/" + quote(folder, safe=""))
        except ComfyError as e:
            if e.status == 404:
                return []
            raise

    async def list_models(self, folder: str = "", query: str = "", limit: int = 50) -> dict:
        """Find model files. With folder (checkpoints, diffusion_models, unet, loras, vae, ...) list that folder.
        Without folder, search every folder for query, or count the files per folder when there is no query.
        Base models may be in checkpoints, diffusion_models or unet."""
        if not folder:
            folders = await self.client.get_json("/models")
            listings = dict(zip(folders, await asyncio.gather(*(self._model_files(f) for f in folders))))
            if not query:
                return {"folders": {f: len(files) for f, files in listings.items() if files}}
            matches = {f: [n for n in files if query.lower() in n.lower()][:limit] for f, files in listings.items()}
            return {"matches": {f: names for f, names in matches.items() if names}}
        try:
            files = await self.client.get_json("/models/" + quote(folder, safe=""))
        except ComfyError as e:
            if e.status != 404:
                raise
            folders = await self.client.get_json("/models")
            raise ComfyError(f"No model folder {folder!r}. Folders: {', '.join(folders)}. Or omit folder to search them all.") from e
        matched = [name for name in files if query.lower() in name.lower()]
        return {"folder": folder, "total": len(files), "matched": len(matched), "items": matched[:limit]}

    async def search_nodes(self, query: str, limit: int = 20, refresh: bool = False) -> dict:
        """Search installed nodes by class name, display name or category. Every word must match. Set refresh after installing nodes."""
        words = query.lower().split()
        nodes = []
        for class_type, info in (await self._object_info_cached(refresh)).items():
            haystack = f"{class_type} {info.get('display_name', '')} {info.get('category', '')}".lower()
            if all(word in haystack for word in words):
                nodes.append({"class_type": class_type, "display_name": info.get("display_name"), "category": info.get("category"), "package": info.get("python_module")})
        return {"matched": len(nodes), "nodes": nodes[:limit]}

    async def get_node_schema(self, class_type: str) -> dict:
        """Show a node's inputs and outputs. Long option lists are cut; use list_models for model names."""
        info = await self.client.get_json("/object_info/" + quote(class_type, safe=""))
        if class_type not in info:
            raise ComfyError(f"No node {class_type!r}. Use search_nodes to find its class name.")
        return _trim_schema(info[class_type])

    async def list_workflows(self) -> dict:
        """List saved workflows and whether each can be run directly."""
        entries = await self.client.get_json("/userdata", dir="workflows", recurse="true", full_info="true")
        workflows = []
        for entry in sorted(entries, key=lambda e: e["path"]):
            if entry["path"].endswith(".json"):
                data = await self.client.get_workflow(entry["path"])
                try:
                    runnable = _runnable_prompt(data) is not None
                except WorkflowError:
                    runnable = False
                workflows.append({"name": entry["path"], "format": detect_format(data), "runnable": runnable})
        return {"workflows": workflows}

    async def read_workflow(self, name: str) -> dict:
        """Show a saved workflow's nodes, with the ids and input names run_workflow overrides refer to."""
        data = await self.client.get_workflow(name)
        file_format = detect_format(data)
        if file_format == "api":
            return {"format": "api", "nodes": summarize_api(data)}
        if file_format == "ui":
            try:
                prompt, note = embedded_prompt(data), EXPORT_NOTE
            except WorkflowError as e:
                prompt, note = None, str(e)
            if prompt is not None:
                return {"format": "ui", "runnable": True, "nodes": summarize_api(prompt)}
            nodes = [{key: node.get(key) for key in ("id", "type", "title", "widgets_values")} for node in data["nodes"]]
            return {"format": "ui", "runnable": False, "nodes": nodes, "note": note}
        raise ComfyError(f"{name} is not a ComfyUI workflow")

    async def run_workflow(self, name: str = "", workflow: dict | None = None, overrides: dict | None = None, randomize_seed: bool = True) -> dict:
        """Queue a saved workflow by name, or an unsaved API-format graph as workflow, and return at once with a prompt_id for get_job.

        overrides maps "node_id.input" to a value, like {"5.text": "a cat", "8.steps": 20}.
        Seeds are randomized unless overridden or randomize_seed is false, so each run
        gives a new image. The seeds used are returned so a result can be reproduced.
        """
        if bool(name) == (workflow is not None):
            raise ComfyError("Pass either name (a saved workflow) or workflow (an API-format graph)")
        if name:
            data = _runnable_prompt(await self.client.get_workflow(name))
            if data is None:
                raise ComfyError(f"{name}: {EXPORT_NOTE}")
        elif detect_format(workflow) == "api":
            data = workflow
        else:
            raise ComfyError(API_SHAPE_NOTE)
        overrides = overrides or {}
        prompt = apply_overrides(data, overrides)
        seeds = {}
        if randomize_seed:
            prompt, seeds = randomize_seeds(prompt, keep=set(overrides))
        prompt_id = str(uuid.uuid4())
        await self.client.submit_prompt(prompt, prompt_id)
        return {"prompt_id": prompt_id, "seeds": seeds}

    async def get_job(self, prompt_id: str, wait_seconds: int = 0) -> dict:
        """Get a job's status, output images and any error. wait_seconds (max 240) blocks until it finishes or the wait ends; call again if still running."""
        deadline = time.monotonic() + min(wait_seconds, MAX_WAIT_SECONDS)
        job = await self._fetch_job(prompt_id)
        while job["status"] not in TERMINAL_STATES and time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            job = await self._fetch_job(prompt_id)
        return job

    async def get_image(self, filename: str, subfolder: str = "", type: str = "output", max_size: int = 768) -> ToolResult:
        """Fetch a generated image, downscaled so it can be looked at. Use the fields from get_job."""
        content = await self.client.get_view(filename, subfolder, type)
        try:
            image = Image.open(io.BytesIO(content))
            image.thumbnail((max_size, max_size))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=85)
        except UnidentifiedImageError as e:
            raise ComfyError(f"{filename} is not an image") from e
        return ToolResult.image(buffer.getvalue(), "image/jpeg")

    async def upload_image(self, path: str) -> dict:
        """Copy a local image into ComfyUI's input folder. Use the returned name for LoadImage inputs."""
        source = Path(path)
        if source.suffix.lower() not in UPLOADABLE:
            raise ComfyError(f"Only {', '.join(sorted(UPLOADABLE))} files can be uploaded")
        if not source.is_file():
            raise ComfyError(f"No file at {path}")
        return await self.client.upload_image(source.name, source.read_bytes())

    async def cancel_job(self, prompt_id: str) -> dict:
        """Cancel a running or queued job. cancelled is false if it had already finished."""
        return await self.client.post(f"/api/jobs/{quote(prompt_id, safe='')}/cancel")

    async def validate_workflow(self, workflow: dict) -> dict:
        """Check an API-format graph against the installed nodes: node types, required inputs, link types, option values and number ranges."""
        if detect_format(workflow) != "api":
            raise ComfyError(API_SHAPE_NOTE)
        result = validate_prompt(workflow, await self._object_info_cached())
        return {"valid": not result["errors"], **result}

    async def save_workflow(self, name: str, workflow: dict, overwrite: bool = False) -> dict:
        """Validate an API-format graph and save it to ComfyUI's workflows folder.

        The file opens on the canvas from the ComfyUI workflows sidebar and runs by name with run_workflow.
        If the user edits it in ComfyUI afterwards, it is no longer runnable here until saved again.
        canvas_warnings names node types whose values may show in the wrong widgets on the canvas;
        running is not affected.
        """
        if detect_format(workflow) != "api":
            raise ComfyError(API_SHAPE_NOTE)
        info = await self._object_info_cached()
        result = validate_prompt(workflow, info)
        if result["errors"]:
            raise ComfyError("Not saved, fix these first:\n" + "\n".join(result["errors"]))
        if not name.endswith(".json"):
            name += ".json"
        try:
            await self.client.save_workflow(name, attach_prompt(to_ui(workflow, info), workflow), overwrite)
        except ComfyError as e:
            if e.status == 409:
                raise ComfyError(f"{name} already exists. Pick another name or pass overwrite=true.") from e
            raise
        saved = {"name": name, "warnings": result["warnings"]}
        if risks := display_risks(workflow, info):
            saved["canvas_warnings"] = risks
        return saved

    async def free_memory(self) -> dict:
        """Unload all models and clear cached results so ComfyUI gives back RAM and VRAM. The next run reloads models, so it starts slower."""
        await self.client.post("/free", {"unload_models": True, "free_memory": True})
        return {"requested": True, "note": "Takes effect once the queue is idle; a running job finishes first."}

    async def describe_image(self, filename: str, subfolder: str = "", type: str = "input") -> dict:
        """Turn an image in ComfyUI's input, output or temp folder into booru-style tags with the installed WD14 tagger.
        For models that cannot see images, or to get tags to copy into a prompt."""
        try:
            tags = await self.client.get_json("/pysssss/wd14tagger/tag", filename=filename, subfolder=subfolder, type=type)
        except ComfyError as e:
            if e.status == 404:
                raise ComfyError(f"Could not tag {filename}: either the file is missing or no tagger is installed "
                                 "(comfyui-wd14-tagger). Without one, only a vision model can look at the image.") from e
            raise
        return {"filename": filename, "tags": tags}

    async def show_in_canvas(self, name: str) -> ToolResult:
        """Open a saved workflow in a new tab on the user's ComfyUI canvas so they can see or edit it."""
        data = await self.client.get_workflow(name)
        if detect_format(data) != "ui":
            raise ComfyError(f"{name} is not a canvas workflow; save it with save_workflow first")
        return ToolResult.of({"opened": name}, event={"type": "open_workflow", "name": name, "workflow": data})
