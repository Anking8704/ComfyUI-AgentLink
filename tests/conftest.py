import io
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

from agentlink.client import ComfyClient
from agentlink.tools import Toolset

API_WORKFLOW = {
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["3", 0]}},
    "8": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 12}},
}
UI_WORKFLOW = {"nodes": [{"id": 1, "type": "KSampler", "title": "Sampler", "widgets_values": [1]}], "links": []}


def reply(make_response):
    async def handler(request):
        return make_response()
    return handler


def png(width, height):
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 128)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeComfy:
    """In-memory ComfyUI answering with the shapes server.py produces."""

    def __init__(self):
        self.posts = []
        self.drop_prompt_connection = False
        self.prompt_error = None
        self.job_states = []
        self.object_info = {
            "KSampler": {
                "display_name": "K采样器",
                "category": "sampling",
                "description": "Denoise a latent",
                "python_module": "nodes",
                "input": {"required": {"sampler_name": [[f"s{i}" for i in range(60)], {}], "steps": ["INT", {"default": 20}]}},
                "output": ["LATENT"],
            },
            "EmptyImage": {"display_name": "Empty Image", "category": "image", "python_module": "nodes", "input": {"required": {"width": ["INT", {"min": 1}]}}, "output": ["IMAGE"]},
            "SaveImage": {"display_name": "Save Image", "category": "image", "description": "", "python_module": "nodes", "input": {"required": {"images": ["IMAGE", {}]}}, "output": [], "output_node": True},
        }
        self.object_info_calls = 0
        self.image = png(2000, 1000)
        self.workflows = {"api.json": API_WORKFLOW, "sub/ui file.json": UI_WORKFLOW}
        self.saved = {}
        self.model_files = {
            "checkpoints": ["sd15.safetensors", "anima_aesthetic.safetensors"],
            "loras": ["anima\turbo.safetensors", "Style_A.safetensors"],
            "diffusion_models": ["anima_baseV10.safetensors"],
            "configs": [],
        }
        self.free_requests = []
        self.has_tagger = True
        self.tag_requests = []

    def app(self):
        app = web.Application()
        app.router.add_get("/system_stats", self.system_stats)
        app.router.add_get("/queue", reply(lambda: web.json_response({"queue_running": [[1]], "queue_pending": [[2], [3]]})))
        app.router.add_get("/models", reply(lambda: web.json_response(list(self.model_files))))
        app.router.add_get("/models/{folder}", self.models)
        app.router.add_get("/object_info", self.all_object_info)
        app.router.add_get("/object_info/{name}", self.one_object_info)
        app.router.add_get("/userdata", self.list_userdata)
        app.router.add_get("/userdata/{file}", self.read_userdata)
        app.router.add_post("/userdata/{file}", self.write_userdata)
        app.router.add_post("/prompt", self.prompt)
        app.router.add_get("/api/jobs/{id}", self.job)
        app.router.add_post("/api/jobs/{id}/cancel", self.cancel)
        app.router.add_get("/view", reply(lambda: web.Response(body=self.image, content_type="image/png")))
        app.router.add_post("/upload/image", self.upload)
        app.router.add_post("/free", self.free)
        app.router.add_get("/pysssss/wd14tagger/tag", self.tag)
        return app

    async def system_stats(self, request):
        return web.json_response({
            "system": {"comfyui_version": "0.42.1", "ram_total": 32 * 2**30, "ram_free": 16 * 2**30},
            "devices": [{"name": "cuda:0 RTX", "type": "cuda", "vram_total": 12 * 2**30, "vram_free": 6 * 2**30}],
        })

    async def models(self, request):
        files = self.model_files.get(request.match_info["folder"])
        return web.json_response(files) if files is not None else web.Response(status=404)

    async def all_object_info(self, request):
        self.object_info_calls += 1
        return web.json_response(self.object_info)

    async def one_object_info(self, request):
        name = request.match_info["name"]
        return web.json_response({name: self.object_info[name]} if name in self.object_info else {})

    async def list_userdata(self, request):
        entries = [{"path": name, "size": 10, "modified": 1} for name in self.workflows]
        return web.json_response(entries + [{"path": "old.json.bak", "size": 1, "modified": 1}])

    async def read_userdata(self, request):
        name = request.match_info["file"].removeprefix("workflows/")
        return web.json_response(self.workflows[name]) if name in self.workflows else web.Response(status=404)

    async def write_userdata(self, request):
        name = request.match_info["file"].removeprefix("workflows/")
        if request.query.get("overwrite") == "false" and name in self.workflows:
            return web.Response(status=409, text="File already exists")
        self.saved[name] = self.workflows[name] = json.loads(await request.read())
        return web.json_response(f"workflows/{name}")

    async def prompt(self, request):
        body = await request.json()
        self.posts.append(body)
        if self.drop_prompt_connection:
            request.transport.close()
            return web.Response()
        if self.prompt_error:
            return web.json_response(self.prompt_error, status=400)
        return web.json_response({"prompt_id": body["prompt_id"], "number": 1, "node_errors": {}})

    async def job(self, request):
        if not self.job_states:
            return web.json_response({"error": "Job not found"}, status=404)
        state = self.job_states.pop(0) if len(self.job_states) > 1 else self.job_states[0]
        return web.json_response(state)

    async def cancel(self, request):
        self.posts.append({"cancel": request.match_info["id"]})
        return web.json_response({"cancelled": True})

    async def upload(self, request):
        form = await request.post()
        self.posts.append({"upload": form["image"].filename})
        return web.json_response({"name": "photo (1).png", "subfolder": "", "type": "input"})

    async def tag(self, request):
        if not self.has_tagger:
            return web.Response(status=404)
        self.tag_requests.append(dict(request.query))
        return web.json_response("1girl, beach, sunset")

    async def free(self, request):
        self.free_requests.append(await request.json())
        return web.Response()


@pytest.fixture
def comfy():
    return FakeComfy()


@pytest.fixture
async def client(comfy):
    server = TestServer(comfy.app())
    await server.start_server()
    comfy_client = ComfyClient(str(server.make_url("")).rstrip("/"))
    yield comfy_client
    await comfy_client.close()
    await server.close()


@pytest.fixture
def toolset(client):
    return Toolset(client, poll_interval=0)
