import copy
import secrets

from .errors import ToolError

SEED_INPUTS = ("seed", "noise_seed")


class WorkflowError(ToolError):
    pass


def detect_format(data):
    if isinstance(data, dict):
        if isinstance(data.get("nodes"), list):
            return "ui"
        if data and all(isinstance(node, dict) and "class_type" in node for node in data.values()):
            return "api"
    return "unknown"


def is_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int)


def apply_overrides(prompt, overrides):
    result = copy.deepcopy(prompt)
    for key, value in overrides.items():
        node_id, _, input_name = key.partition(".")
        if not input_name:
            raise WorkflowError(f"Bad override key {key!r}: expected node_id.input, like 5.text")
        if node_id not in result:
            raise WorkflowError(f"Workflow has no node {node_id}")
        inputs = result[node_id]["inputs"]
        if input_name not in inputs:
            raise WorkflowError(f"Node {node_id} has no input {input_name!r}. Inputs: {', '.join(inputs)}")
        if is_link(inputs[input_name]):
            raise WorkflowError(f"{key} is a connection to another node, not a value")
        inputs[input_name] = value
    return result


def randomize_seeds(prompt, keep):
    result = copy.deepcopy(prompt)
    seeds = {}
    for node_id, node in result.items():
        for name in SEED_INPUTS:
            key = f"{node_id}.{name}"
            value = node["inputs"].get(name)
            if key not in keep and isinstance(value, int) and not isinstance(value, bool):
                node["inputs"][name] = seeds[key] = secrets.randbelow(2**53)
    return result, seeds


def summarize_api(prompt):
    nodes = []
    for node_id, node in prompt.items():
        inputs = node.get("inputs", {})
        nodes.append({
            "id": node_id,
            "class_type": node["class_type"],
            "title": node.get("_meta", {}).get("title"),
            "values": {name: value for name, value in inputs.items() if not is_link(value)},
            "connections": {name: f"{value[0]}:{value[1]}" for name, value in inputs.items() if is_link(value)},
        })
    return nodes
