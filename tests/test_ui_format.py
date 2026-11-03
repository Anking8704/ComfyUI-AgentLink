import copy

import pytest

from agentlink.ui_format import attach_prompt, display_risks, embedded_prompt, to_ui, widget_slots
from agentlink.workflow import WorkflowError

OBJECT_INFO = {
    "Loader": {
        "input": {"required": {"ckpt_name": [["a.safetensors", "b.safetensors"], {}]}},
        "input_order": {"required": ["ckpt_name"]},
        "output": ["MODEL", "CLIP"], "output_name": ["MODEL", "CLIP"],
    },
    "Int": {"input": {"required": {"value": ["INT", {"default": 0}]}}, "input_order": {"required": ["value"]}, "output": ["INT"], "output_name": ["INT"]},
    "Sampler": {
        "input": {
            "required": {
                "model": ["MODEL", {}],
                "seed": ["INT", {"default": 0, "control_after_generate": True}],
                "steps": ["INT", {"default": 20}],
                "sampler_name": ["COMBO", {"options": ["euler", "dpmpp_2m"]}],
            },
            "optional": {"denoise": ["FLOAT", {"default": 1.0}], "note": ["STRING", {"forceInput": True}]},
        },
        "input_order": {"required": ["model", "seed", "steps", "sampler_name"], "optional": ["denoise", "note"]},
        "output": ["LATENT"], "output_name": ["LATENT"],
    },
    "Load": {
        "input": {"required": {"image": [["a.png", "b.png"], {"image_upload": True}]}},
        "input_order": {"required": ["image"]},
        "output": ["IMAGE", "MASK"], "output_name": ["IMAGE", "MASK"],
    },
    "Save": {
        "input": {"required": {"samples": ["LATENT", {}], "filename_prefix": ["STRING", {"default": "ComfyUI"}]}},
        "input_order": {"required": ["samples", "filename_prefix"]},
        "output": [], "output_name": [], "output_node": True,
    },
}

PROMPT = {
    "1": {"class_type": "Loader", "inputs": {"ckpt_name": "b.safetensors"}},
    "3": {"class_type": "Int", "inputs": {"value": 30}},
    "2": {"class_type": "Sampler", "inputs": {"model": ["1", 0], "seed": 5, "steps": ["3", 0], "sampler_name": "dpmpp_2m"}},
    "4": {"class_type": "Load", "inputs": {"image": "b.png"}},
    "5": {"class_type": "Save", "inputs": {"samples": ["2", 0], "filename_prefix": "out"}},
}


def node(ui, node_id):
    return next(n for n in ui["nodes"] if n["id"] == node_id)


def test_widget_slots_follow_input_order_with_frontend_extras():
    assert [name for name, _ in widget_slots(OBJECT_INFO["Sampler"])] == ["seed", "control_after_generate", "steps", "sampler_name", "denoise"]
    assert widget_slots(OBJECT_INFO["Load"]) == [("image", "a.png"), ("upload", "image")]


def test_widget_values_use_prompt_values_and_defaults():
    ui = to_ui(PROMPT, OBJECT_INFO)
    assert node(ui, 2)["widgets_values"] == [5, "fixed", 20, "dpmpp_2m", 1.0]
    assert node(ui, 4)["widgets_values"] == ["b.png", "image"]
    assert node(ui, 5)["widgets_values"] == ["out"]


def test_links_become_sockets_and_link_records():
    ui = to_ui(PROMPT, OBJECT_INFO)
    sampler_inputs = {i["name"]: i for i in node(ui, 2)["inputs"]}
    model_link = sampler_inputs["model"]["link"]
    steps_link = sampler_inputs["steps"]["link"]
    assert sampler_inputs["steps"]["widget"] == {"name": "steps"}
    assert "seed" not in sampler_inputs
    links = {link[0]: link for link in ui["links"]}
    assert links[model_link] == [model_link, 1, 0, 2, 0, "MODEL"]
    # Sockets come first (model, note), then linked widgets, matching the frontend's slot order.
    assert links[steps_link] == [steps_link, 3, 0, 2, 2, "INT"]
    assert node(ui, 1)["outputs"][0]["links"] == [model_link]
    assert ui["last_link_id"] == len(ui["links"]) == 3


def test_force_input_strings_are_sockets_not_widgets():
    assert "note" not in [name for name, _ in widget_slots(OBJECT_INFO["Sampler"])]


def test_layout_places_consumers_right_of_their_sources():
    ui = to_ui(PROMPT, OBJECT_INFO)
    assert node(ui, 1)["pos"][0] < node(ui, 2)["pos"][0] < node(ui, 5)["pos"][0]
    assert node(ui, 1)["pos"] != node(ui, 3)["pos"]


def test_non_numeric_ids_are_renumbered():
    prompt = {"a": {"class_type": "Int", "inputs": {"value": 1}}, "b": {"class_type": "Save", "inputs": {"samples": ["a", 0], "filename_prefix": "x"}}}
    ui = to_ui(prompt, OBJECT_INFO)
    assert sorted(n["id"] for n in ui["nodes"]) == [1, 2]
    assert ui["last_node_id"] == 2


def test_embedded_prompt_round_trips():
    ui = attach_prompt(to_ui(PROMPT, OBJECT_INFO), PROMPT)
    assert embedded_prompt(ui) == PROMPT


def test_plain_ui_file_has_no_embedded_prompt():
    assert embedded_prompt(to_ui(PROMPT, OBJECT_INFO)) is None


def test_editing_on_canvas_invalidates_embedded_prompt():
    ui = attach_prompt(to_ui(PROMPT, OBJECT_INFO), PROMPT)
    edited = copy.deepcopy(ui)
    node(edited, 2)["widgets_values"][2] = 40
    with pytest.raises(WorkflowError, match="edited"):
        embedded_prompt(edited)


def test_moving_nodes_does_not_count_as_editing():
    ui = attach_prompt(to_ui(PROMPT, OBJECT_INFO), PROMPT)
    node(ui, 2)["pos"] = [999, 999]
    assert embedded_prompt(ui) == PROMPT


def test_empty_combo_gets_empty_default():
    assert widget_slots({"input": {"required": {"model": [[], {}]}}}) == [("model", "")]


def test_upload_button_comes_after_all_other_widgets():
    info = {"input": {"required": {"image": [["a.png"], {"image_upload": True}], "channel": [["alpha", "red"], {}]}}}
    assert widget_slots(info) == [("image", "a.png"), ("channel", "alpha"), ("upload", "image")]


def test_audio_upload_button_has_empty_value():
    info = {"input": {"required": {"audio": ["COMBO", {"options": [], "audio_upload": True}]}}}
    assert widget_slots(info) == [("audio", ""), ("upload", "")]


def test_seed_named_inputs_get_a_control_widget_without_the_flag():
    info = {"input": {"required": {"seed": ["INT", {"default": 0}], "noise_seed": ["INT", {}], "width": ["INT", {"default": 8}]}}}
    assert [name for name, _ in widget_slots(info)] == ["seed", "control_after_generate", "noise_seed", "control_after_generate", "width"]


def test_display_risks_name_nodes_with_frontend_driven_inputs():
    info = {
        **OBJECT_INFO,
        "Resize": {"input": {"required": {"resize_type": ["COMFY_DYNAMICCOMBO_V3", {}]}}, "output": ["IMAGE"]},
        "Overlay": {"input": {"required": {"color": ["STRING", {"widgetType": "COLOR"}]}}, "output": ["IMAGE"]},
    }
    prompt = {**PROMPT, "6": {"class_type": "Resize", "inputs": {}}, "7": {"class_type": "Overlay", "inputs": {}}}
    assert display_risks(prompt, info) == ["Overlay", "Resize"]


def test_multiline_text_nodes_get_room_for_the_text():
    info = {
        "Prompt": {"input": {"required": {"text": ["STRING", {"multiline": True}]}}, "output": ["CONDITIONING"]},
        "Name": {"input": {"required": {"text": ["STRING", {}]}}, "output": ["STRING"]},
    }
    ui = to_ui({"1": {"class_type": "Prompt", "inputs": {"text": "a"}}, "2": {"class_type": "Name", "inputs": {"text": "a"}}}, info)
    assert node(ui, 1)["size"][0] > node(ui, 2)["size"][0]
    assert node(ui, 1)["size"][1] >= node(ui, 2)["size"][1] + 100
