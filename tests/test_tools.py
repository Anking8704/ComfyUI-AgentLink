import base64
import io

import pytest
from PIL import Image


async def call(toolset, tool, **args):
    return await toolset.call(tool, args)


async def data(toolset, tool, **args):
    result = await call(toolset, tool, **args)
    assert not result.is_error, result.content[0]["text"]
    return result.structured


async def error(toolset, tool, **args):
    result = await call(toolset, tool, **args)
    assert result.is_error
    return result.content[0]["text"]


def test_exposes_the_planned_tools(toolset):
    assert set(toolset.tools) == {
        "comfy_status", "list_models", "search_nodes", "get_node_schema", "list_workflows", "read_workflow",
        "run_workflow", "get_job", "get_image", "upload_image", "cancel_job",
        "validate_workflow", "save_workflow", "free_memory", "describe_image",
    }


def test_chat_toolset_adds_canvas_tool(client):
    from agentlink.tools import Toolset
    assert "show_in_canvas" in Toolset(client, chat=True).tools


def test_schemas_follow_signatures(toolset):
    schemas = {s["name"]: s for s in toolset.schemas()}
    run = schemas["run_workflow"]["input_schema"]
    assert run["properties"]["name"] == {"type": "string"}
    assert run["properties"]["workflow"] == {"type": "object"}
    assert run["properties"]["randomize_seed"] == {"type": "boolean"}
    assert run["required"] == []
    assert schemas["get_node_schema"]["input_schema"]["required"] == ["class_type"]
    assert schemas["run_workflow"]["description"].startswith("Queue a saved workflow")


async def test_unknown_tool_is_an_error_result(toolset):
    assert "no_such_tool" in await error(toolset, "no_such_tool")


async def test_missing_required_argument_is_an_error_result(toolset):
    assert "class_type" in await error(toolset, "get_node_schema")


async def test_status_reports_offline_instead_of_failing(comfy):
    from agentlink.client import ComfyClient
    from agentlink.tools import Toolset
    offline = ComfyClient("http://127.0.0.1:9")
    assert (await data(Toolset(offline), "comfy_status"))["online"] is False
    await offline.close()


async def test_status_summarises_hardware_and_queue(toolset):
    status = await data(toolset, "comfy_status")
    assert status["online"] is True
    assert status["queue"] == {"running": 1, "pending": 2}
    assert status["devices"] == [{"name": "cuda:0 RTX", "vram_free_gb": 6.0, "vram_total_gb": 12.0}]


async def test_list_models_without_folder_counts_every_folder(toolset):
    assert await data(toolset, "list_models") == {"folders": {"checkpoints": 2, "loras": 2, "diffusion_models": 1}}


async def test_list_models_query_without_folder_searches_every_folder(toolset):
    result = await data(toolset, "list_models", query="ANIMA")
    assert result == {"matches": {"checkpoints": ["anima_aesthetic.safetensors"], "loras": ["anima\turbo.safetensors"],
                                  "diffusion_models": ["anima_baseV10.safetensors"]}}


async def test_list_models_filters_case_insensitively(toolset):
    result = await data(toolset, "list_models", folder="loras", query="style")
    assert result == {"folder": "loras", "total": 2, "matched": 1, "items": ["Style_A.safetensors"]}


async def test_search_nodes_matches_every_word_across_fields(toolset):
    result = await data(toolset, "search_nodes", query="采样 sampling")
    assert [n["class_type"] for n in result["nodes"]] == ["KSampler"]


async def test_search_nodes_caches_object_info(toolset, comfy):
    await call(toolset, "search_nodes", query="save")
    await call(toolset, "search_nodes", query="sampler")
    assert comfy.object_info_calls == 1


async def test_node_schema_truncates_long_combos(toolset):
    schema = await data(toolset, "get_node_schema", class_type="KSampler")
    combo = schema["input"]["required"]["sampler_name"]
    assert len(combo[0]) == 50
    assert combo[1]["total_options"] == 60


async def test_unknown_node_schema_points_at_search(toolset):
    assert "search_nodes" in await error(toolset, "get_node_schema", class_type="Nope")


async def test_list_workflows_labels_format_and_skips_backups(toolset):
    result = await data(toolset, "list_workflows")
    assert result["workflows"] == [
        {"name": "api.json", "format": "api", "runnable": True},
        {"name": "sub/ui file.json", "format": "ui", "runnable": False},
    ]


async def test_read_api_workflow_returns_node_summary(toolset):
    result = await data(toolset, "read_workflow", name="api.json")
    assert result["format"] == "api"
    assert result["nodes"][1]["values"] == {"seed": 42, "steps": 12}


async def test_read_ui_workflow_explains_it_cannot_run(toolset):
    result = await data(toolset, "read_workflow", name="sub/ui file.json")
    assert result["format"] == "ui"
    assert result["nodes"] == [{"id": 1, "type": "KSampler", "title": "Sampler", "widgets_values": [1]}]
    assert "Export" in result["note"]


async def test_run_workflow_submits_overrides_and_random_seed(toolset, comfy):
    result = await data(toolset, "run_workflow", name="api.json", overrides={"5.text": "dog"})
    sent = comfy.posts[0]
    assert sent["prompt"]["5"]["inputs"]["text"] == "dog"
    assert sent["prompt"]["8"]["inputs"]["seed"] == result["seeds"]["8.seed"]
    assert sent["prompt_id"] == result["prompt_id"]


async def test_run_workflow_keeps_seed_when_asked(toolset, comfy):
    result = await data(toolset, "run_workflow", name="api.json", randomize_seed=False)
    assert comfy.posts[0]["prompt"]["8"]["inputs"]["seed"] == 42
    assert result["seeds"] == {}


async def test_run_workflow_override_seed_wins_over_randomizing(toolset, comfy):
    await data(toolset, "run_workflow", name="api.json", overrides={"8.seed": 5})
    assert comfy.posts[0]["prompt"]["8"]["inputs"]["seed"] == 5


async def test_run_workflow_refuses_ui_format_without_submitting(toolset, comfy):
    assert "Export" in await error(toolset, "run_workflow", name="sub/ui file.json")
    assert comfy.posts == []


async def test_run_workflow_surfaces_validation_errors_by_node(toolset, comfy):
    comfy.prompt_error = {
        "error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation", "details": ""},
        "node_errors": {"8": {"class_type": "KSampler", "errors": [{"message": "Value not in list", "details": "sampler_name: 'x' not in [...]"}]}},
    }
    message = await error(toolset, "run_workflow", name="api.json")
    assert "8 (KSampler)" in message and "sampler_name" in message


async def test_get_job_lists_output_files(toolset, comfy):
    comfy.job_states = [{"id": "a", "status": "completed", "outputs": {"10": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}}}]
    job = await data(toolset, "get_job", prompt_id="a")
    assert job["status"] == "completed"
    assert job["images"] == [{"filename": "x.png", "subfolder": "", "type": "output", "node_id": "10"}]


async def test_get_job_reports_failure_without_traceback(toolset, comfy):
    comfy.job_states = [{"id": "a", "status": "failed", "execution_error": {
        "node_id": "8", "node_type": "KSampler", "exception_type": "OOM", "exception_message": "out of memory", "traceback": ["x"] * 100}}]
    job = await data(toolset, "get_job", prompt_id="a")
    assert job["error"] == {"node_id": "8", "node_type": "KSampler", "exception_type": "OOM", "exception_message": "out of memory"}


async def test_get_job_waits_until_finished(toolset, comfy):
    comfy.job_states = [{"id": "a", "status": "pending"}, {"id": "a", "status": "in_progress"}, {"id": "a", "status": "completed"}]
    assert (await data(toolset, "get_job", prompt_id="a", wait_seconds=5))["status"] == "completed"


async def test_get_job_returns_current_state_when_wait_expires(toolset, comfy):
    comfy.job_states = [{"id": "a", "status": "in_progress"}]
    assert (await data(toolset, "get_job", prompt_id="a", wait_seconds=0))["status"] == "in_progress"


async def test_get_job_unknown_id(toolset):
    assert (await data(toolset, "get_job", prompt_id="missing"))["status"] == "not_found"


async def test_get_image_returns_downscaled_jpeg(toolset):
    result = await call(toolset, "get_image", filename="x.png")
    block = result.content[0]
    assert block["mime"] == "image/jpeg"
    image = Image.open(io.BytesIO(base64.b64decode(block["data"])))
    assert image.size == (768, 384)


async def test_get_image_rejects_non_images(toolset, comfy):
    comfy.image = b"not an image"
    assert "not an image" in await error(toolset, "get_image", filename="x.mp4")


async def test_upload_image_returns_name_to_use(toolset, comfy, tmp_path):
    photo = tmp_path / "photo.png"
    photo.write_bytes(comfy.image)
    result = await data(toolset, "upload_image", path=str(photo))
    assert result["name"] == "photo (1).png"


@pytest.mark.parametrize("filename", ["secrets.txt", "missing.png"])
async def test_upload_image_refuses_bad_paths(toolset, comfy, tmp_path, filename):
    if filename.endswith(".txt"):
        (tmp_path / filename).write_text("x")
    await error(toolset, "upload_image", path=str(tmp_path / filename))
    assert comfy.posts == []


async def test_cancel_job(toolset, comfy):
    assert await data(toolset, "cancel_job", prompt_id="a") == {"cancelled": True}
    assert comfy.posts == [{"cancel": "a"}]


BUILT = {
    "1": {"class_type": "EmptyImage", "inputs": {"width": 64}},
    "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}


async def test_validate_workflow_reports_problems(toolset):
    result = await data(toolset, "validate_workflow", workflow={**BUILT, "1": {"class_type": "EmptyImage", "inputs": {"width": 0}}})
    assert result == {"valid": False, "errors": ["1.width: 0 is below min 1"], "warnings": []}


async def test_validate_workflow_accepts_good_graph(toolset):
    assert (await data(toolset, "validate_workflow", workflow=BUILT))["valid"] is True


async def test_save_workflow_writes_canvas_file_carrying_the_prompt(toolset, comfy):
    result = await data(toolset, "save_workflow", name="built/new", workflow=BUILT)
    assert result["name"] == "built/new.json"
    saved = comfy.saved["built/new.json"]
    assert [n["type"] for n in saved["nodes"]] == ["EmptyImage", "SaveImage"]
    assert saved["extra"]["comfypilot"]["prompt"] == BUILT
    workflows = (await data(toolset, "list_workflows"))["workflows"]
    assert {"name": "built/new.json", "format": "ui", "runnable": True} in workflows


async def test_saved_canvas_file_runs_by_name(toolset, comfy):
    await data(toolset, "save_workflow", name="built/new", workflow=BUILT)
    await data(toolset, "run_workflow", name="built/new.json", overrides={"1.width": 32})
    assert comfy.posts[0]["prompt"]["1"]["inputs"]["width"] == 32


async def test_read_saved_canvas_file_shows_runnable_nodes(toolset, comfy):
    await data(toolset, "save_workflow", name="built/new", workflow=BUILT)
    result = await data(toolset, "read_workflow", name="built/new.json")
    assert result["runnable"] is True
    assert result["nodes"][0]["values"] == {"width": 64}


async def test_canvas_edits_stop_the_saved_prompt_from_running(toolset, comfy):
    await data(toolset, "save_workflow", name="built/new", workflow=BUILT)
    comfy.workflows["built/new.json"]["nodes"][0]["widgets_values"] = [128]
    assert "edited" in await error(toolset, "run_workflow", name="built/new.json")
    assert comfy.posts == []
    workflows = (await data(toolset, "list_workflows"))["workflows"]
    assert {"name": "built/new.json", "format": "ui", "runnable": False} in workflows


async def test_save_workflow_refuses_invalid_graph(toolset, comfy):
    message = await error(toolset, "save_workflow", name="bad.json", workflow={"1": {"class_type": "Nope", "inputs": {}}})
    assert "unknown node type" in message
    assert comfy.saved == {}


async def test_save_workflow_does_not_overwrite_by_default(toolset, comfy):
    assert "overwrite" in await error(toolset, "save_workflow", name="api.json", workflow=BUILT)
    await data(toolset, "save_workflow", name="api.json", workflow=BUILT, overwrite=True)
    assert comfy.saved["api.json"]["extra"]["comfypilot"]["prompt"] == BUILT


async def test_run_workflow_accepts_an_unsaved_graph(toolset, comfy):
    await data(toolset, "run_workflow", workflow=BUILT)
    assert comfy.posts[0]["prompt"] == BUILT


async def test_run_workflow_needs_exactly_one_source(toolset, comfy):
    await error(toolset, "run_workflow")
    await error(toolset, "run_workflow", name="api.json", workflow=BUILT)
    assert comfy.posts == []


async def test_free_memory_unloads_models(toolset, comfy):
    result = await data(toolset, "free_memory")
    assert comfy.free_requests == [{"unload_models": True, "free_memory": True}]
    assert "idle" in result["note"]


async def test_show_in_canvas_sends_saved_file_to_the_page(client, comfy):
    from agentlink.tools import Toolset
    chat = Toolset(client, chat=True)
    await chat.call("save_workflow", {"name": "built/new", "workflow": BUILT})
    result = await chat.call("show_in_canvas", {"name": "built/new.json"})
    assert not result.is_error
    assert result.event["type"] == "open_workflow"
    assert result.event["name"] == "built/new.json"
    assert result.event["workflow"]["nodes"]


async def test_unknown_model_folder_names_the_real_ones(toolset):
    message = await error(toolset, "list_models", folder="unet")
    assert "unet" in message and "diffusion_models" in message


async def test_describe_image_asks_the_installed_tagger(toolset, comfy):
    result = await data(toolset, "describe_image", filename="ref.png")
    assert result == {"filename": "ref.png", "tags": "1girl, beach, sunset"}
    assert comfy.tag_requests == [{"filename": "ref.png", "subfolder": "", "type": "input"}]


async def test_describe_image_without_a_tagger_says_what_to_do(toolset, comfy):
    comfy.has_tagger = False
    assert "vision" in await error(toolset, "describe_image", filename="ref.png")
