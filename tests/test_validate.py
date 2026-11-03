from agentlink.validate import validate_prompt

OBJECT_INFO = {
    "Loader": {"input": {"required": {"ckpt_name": [["a.safetensors", "b.safetensors"], {}]}}, "output": ["MODEL", "CLIP", "VAE"]},
    "Encode": {"input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP", {}]}}, "output": ["CONDITIONING"]},
    "Sampler": {
        "input": {
            "required": {
                "model": ["MODEL", {}],
                "positive": ["CONDITIONING", {}],
                "steps": ["INT", {"default": 20, "min": 1, "max": 100}],
                "sampler_name": ["COMBO", {"options": ["euler", "dpmpp_2m"]}],
            },
            "optional": {"denoise": ["FLOAT", {"min": 0.0, "max": 1.0}]},
        },
        "output": ["LATENT"],
    },
    "Save": {"input": {"required": {"samples": ["LATENT,IMAGE", {}]}}, "output": [], "output_node": True},
}


def graph(**changes):
    prompt = {
        "1": {"class_type": "Loader", "inputs": {"ckpt_name": "a.safetensors"}},
        "2": {"class_type": "Encode", "inputs": {"text": "cat", "clip": ["1", 1]}},
        "3": {"class_type": "Sampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "steps": 20, "sampler_name": "euler"}},
        "4": {"class_type": "Save", "inputs": {"samples": ["3", 0]}},
    }
    for key, value in changes.items():
        node_id, _, name = key.partition("_")
        if value is None:
            del prompt[node_id]["inputs"][name]
        else:
            prompt[node_id]["inputs"][name] = value
    return prompt


def errors_of(prompt):
    return validate_prompt(prompt, OBJECT_INFO)["errors"]


def test_valid_graph_has_no_problems():
    assert validate_prompt(graph(), OBJECT_INFO) == {"errors": [], "warnings": []}


def test_unknown_node_type():
    prompt = graph()
    prompt["5"] = {"class_type": "Nope", "inputs": {}}
    assert errors_of(prompt) == ["5: unknown node type 'Nope'"]


def test_missing_required_input():
    assert errors_of(graph(**{"3_steps": None})) == ["3.steps: required input is missing"]


def test_optional_input_may_be_absent_or_set():
    assert errors_of(graph(**{"3_denoise": 0.5})) == []


def test_link_to_missing_node():
    assert errors_of(graph(**{"3_model": ["9", 0]})) == ["3.model: links to missing node 9"]


def test_link_to_missing_output_slot():
    assert errors_of(graph(**{"3_model": ["1", 5]})) == ["3.model: node 1 (Loader) has no output 5"]


def test_link_type_mismatch():
    assert errors_of(graph(**{"3_model": ["1", 2]})) == ["3.model: expects MODEL but node 1 output 2 is VAE"]


def test_input_accepting_several_types():
    assert errors_of(graph()) == []


def test_combo_value_must_be_an_option():
    assert errors_of(graph(**{"1_ckpt_name": "c.safetensors"})) == ["1.ckpt_name: 'c.safetensors' is not an option"]


def test_new_style_combo_checked_too():
    assert errors_of(graph(**{"3_sampler_name": "lms"})) == ["3.sampler_name: 'lms' is not an option"]


def test_number_out_of_range():
    assert errors_of(graph(**{"3_steps": 500})) == ["3.steps: 500 is above max 100"]


def test_number_that_is_not_a_number():
    assert errors_of(graph(**{"3_steps": "many"})) == ["3.steps: 'many' is not a number"]


def test_value_where_a_connection_is_needed():
    assert errors_of(graph(**{"3_model": "a.safetensors"})) == ["3.model: needs a connection from a MODEL output"]


def test_unknown_input_is_only_a_warning():
    result = validate_prompt(graph(**{"3_stepz": 1}), OBJECT_INFO)
    assert result == {"errors": [], "warnings": ["3.stepz: Sampler has no input named stepz; ComfyUI will ignore it"]}


def test_graph_without_output_node():
    prompt = graph()
    del prompt["4"]
    assert errors_of(prompt) == ["no output node such as SaveImage or PreviewImage, so nothing would run"]
