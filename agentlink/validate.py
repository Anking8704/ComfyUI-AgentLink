from .workflow import is_link

VALUE_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


def _combo_options(spec):
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1:
        return spec[1].get("options")
    return None


def _types_match(expected, actual):
    if expected == "*" or actual == "*":
        return True
    return bool(set(expected.split(",")) & set(actual.split(",")))


def _check_link(key, spec, value, prompt, object_info):
    source_id, slot = str(value[0]), value[1]
    if source_id not in prompt:
        return f"{key}: links to missing node {source_id}"
    source_type = prompt[source_id].get("class_type")
    outputs = object_info.get(source_type, {}).get("output")
    if outputs is None:
        return None
    if slot >= len(outputs):
        return f"{key}: node {source_id} ({source_type}) has no output {slot}"
    if isinstance(spec[0], str) and isinstance(outputs[slot], str) and not _types_match(spec[0], outputs[slot]):
        return f"{key}: expects {spec[0]} but node {source_id} output {slot} is {outputs[slot]}"
    return None


def _check_value(key, spec, value):
    options = _combo_options(spec)
    if options is not None:
        return None if value in options else f"{key}: {value!r} is not an option"
    kind = spec[0]
    if kind not in VALUE_TYPES:
        return f"{key}: needs a connection from a {kind} output"
    if kind in ("INT", "FLOAT"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f"{key}: {value!r} is not a number"
        limits = spec[1] if len(spec) > 1 else {}
        if "min" in limits and number < limits["min"]:
            return f"{key}: {value} is below min {limits['min']}"
        if "max" in limits and number > limits["max"]:
            return f"{key}: {value} is above max {limits['max']}"
    return None


def validate_prompt(prompt, object_info):
    """Check an API-format graph against installed node definitions before it is saved or run."""
    errors, warnings = [], []
    has_output = False
    for node_id, node in prompt.items():
        class_type = node.get("class_type")
        info = object_info.get(class_type)
        if info is None:
            errors.append(f"{node_id}: unknown node type {class_type!r}")
            continue
        has_output = has_output or info.get("output_node", False)
        required = info["input"].get("required", {})
        known = {**required, **info["input"].get("optional", {})}
        inputs = node.get("inputs", {})
        for name in required:
            if name not in inputs:
                errors.append(f"{node_id}.{name}: required input is missing")
        for name, value in inputs.items():
            key = f"{node_id}.{name}"
            if name not in known:
                warnings.append(f"{key}: {class_type} has no input named {name}; ComfyUI will ignore it")
                continue
            problem = _check_link(key, known[name], value, prompt, object_info) if is_link(value) else _check_value(key, known[name], value)
            if problem:
                errors.append(problem)
    if not has_output:
        errors.append("no output node such as SaveImage or PreviewImage, so nothing would run")
    return {"errors": errors, "warnings": warnings}
