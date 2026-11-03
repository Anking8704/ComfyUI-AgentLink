import copy

import pytest

from agentlink.workflow import (
    WorkflowError,
    apply_overrides,
    detect_format,
    randomize_seeds,
    summarize_api,
)

PROMPT = {
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["3", 0]}, "_meta": {"title": "Positive"}},
    "8": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 12, "model": ["2", 0]}},
    "9": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 7}},
    "10": {"class_type": "Linked", "inputs": {"seed": ["11", 0]}},
}


def test_detects_api_format():
    assert detect_format(PROMPT) == "api"


def test_detects_ui_format():
    assert detect_format({"nodes": [], "links": [], "version": 0.4}) == "ui"


def test_unrecognised_json_is_unknown():
    assert detect_format({"foo": "bar"}) == "unknown"
    assert detect_format([1, 2]) == "unknown"


def test_override_changes_literal_input_without_touching_original():
    original = copy.deepcopy(PROMPT)
    result = apply_overrides(PROMPT, {"5.text": "dog", "8.steps": 20})
    assert result["5"]["inputs"]["text"] == "dog"
    assert result["8"]["inputs"]["steps"] == 20
    assert PROMPT == original


def test_override_rejects_unknown_node():
    with pytest.raises(WorkflowError, match="node 99"):
        apply_overrides(PROMPT, {"99.text": "x"})


def test_override_rejects_unknown_input_and_lists_valid_ones():
    with pytest.raises(WorkflowError, match="seed, steps"):
        apply_overrides(PROMPT, {"8.stepz": 20})


def test_override_rejects_malformed_key():
    with pytest.raises(WorkflowError, match="node_id.input"):
        apply_overrides(PROMPT, {"steps": 20})


def test_override_refuses_to_replace_a_connection():
    with pytest.raises(WorkflowError, match="connection"):
        apply_overrides(PROMPT, {"5.clip": "x"})


def test_randomize_changes_literal_seeds_and_reports_them():
    result, seeds = randomize_seeds(PROMPT, keep=set())
    assert seeds == {"8.seed": result["8"]["inputs"]["seed"], "9.noise_seed": result["9"]["inputs"]["noise_seed"]}
    assert result["8"]["inputs"]["seed"] != 42
    assert result["9"]["inputs"]["noise_seed"] != 7


def test_randomize_leaves_linked_seed_alone():
    result, _ = randomize_seeds(PROMPT, keep=set())
    assert result["10"]["inputs"]["seed"] == ["11", 0]


def test_randomize_keeps_seeds_the_caller_set():
    result, seeds = randomize_seeds(PROMPT, keep={"8.seed"})
    assert result["8"]["inputs"]["seed"] == 42
    assert "8.seed" not in seeds


def test_summary_separates_values_from_connections():
    node = next(n for n in summarize_api(PROMPT) if n["id"] == "5")
    assert node == {
        "id": "5",
        "class_type": "CLIPTextEncode",
        "title": "Positive",
        "values": {"text": "cat"},
        "connections": {"clip": "3:0"},
    }
