"""Turn an API-format prompt into a canvas (UI-format) workflow the ComfyUI sidebar can open."""
import copy

from .validate import VALUE_TYPES, _combo_options
from .workflow import WorkflowError, is_link

COLUMN_WIDTH = 480
NODE_WIDTH = 320
TEXT_NODE_WIDTH = 420
TEXT_BOX_HEIGHT = 120
# Values the frontend stores for its upload buttons, which it always puts after the other widgets.
UPLOAD_WIDGETS = {"image_upload": "image", "video_upload": "image", "audio_upload": ""}
# The frontend adds a seed control to these even when the node does not ask for one.
SEED_NAMES = {"seed", "noise_seed"}
FRONTEND_DRIVEN_TYPES = {"COMFY_DYNAMICCOMBO_V3", "COMFY_AUTOGROW_V3"}


def _ordered_inputs(info):
    order = info.get("input_order", {})
    for group in ("required", "optional"):
        specs = info["input"].get(group, {})
        for name in order.get(group, specs):
            yield name, specs[name]


def _is_widget(spec):
    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    return isinstance(spec[0], list) or (spec[0] in VALUE_TYPES and not options.get("forceInput"))


def _default(spec):
    options = _combo_options(spec)
    extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if "default" in extra:
        return extra["default"]
    if options is not None:
        return options[0] if options else ""
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(spec[0])


def widget_slots(info):
    """Widgets the frontend creates for a node, in widgets_values order, with default values."""
    slots, uploads = [], []
    for name, spec in _ordered_inputs(info):
        if not _is_widget(spec):
            continue
        slots.append((name, _default(spec)))
        extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        if extra.get("control_after_generate") or (spec[0] == "INT" and name in SEED_NAMES):
            slots.append(("control_after_generate", "fixed"))
        uploads += [("upload", value) for flag, value in UPLOAD_WIDGETS.items() if extra.get(flag)]
    return slots + uploads


def _socket_type(spec):
    return "COMBO" if isinstance(spec[0], list) else spec[0]


def _depths(prompt):
    depths = {}

    def depth(node_id, seen=()):
        if node_id not in depths:
            sources = [str(v[0]) for v in prompt[node_id]["inputs"].values() if is_link(v) and str(v[0]) in prompt and str(v[0]) not in seen]
            depths[node_id] = 1 + max((depth(s, seen + (node_id,)) for s in sources), default=-1)
        return depths[node_id]

    for node_id in prompt:
        depth(node_id)
    return depths


def to_ui(prompt, object_info):
    numeric = all(node_id.isdigit() for node_id in prompt)
    ids = {node_id: int(node_id) if numeric else i for i, node_id in enumerate(prompt, 1)}
    nodes, links = {}, []

    for order, (node_id, api_node) in enumerate(prompt.items()):
        info = object_info[api_node["class_type"]]
        values = api_node["inputs"]
        sockets = [(name, spec) for name, spec in _ordered_inputs(info) if not _is_widget(spec)]
        linked_widgets = [(name, spec) for name, spec in _ordered_inputs(info) if _is_widget(spec) and is_link(values.get(name))]
        inputs = [{"name": name, "type": _socket_type(spec), "link": None} for name, spec in sockets]
        inputs += [{"name": name, "type": _socket_type(spec), "widget": {"name": name}, "link": None} for name, spec in linked_widgets]
        widgets_values = []
        for name, default in widget_slots(info):
            value = values.get(name, default)
            widgets_values.append(default if is_link(value) else value)
        output_types = ["COMBO" if isinstance(t, list) else t for t in info.get("output", [])]
        output_names = info.get("output_name") or output_types
        text_boxes = sum(1 for _, spec in _ordered_inputs(info) if spec[0] == "STRING" and len(spec) > 1 and spec[1].get("multiline"))
        nodes[node_id] = {
            "id": ids[node_id],
            "type": api_node["class_type"],
            "pos": [0, 0],
            "size": [TEXT_NODE_WIDTH if text_boxes else NODE_WIDTH, 46 + 22 * max(len(inputs), len(output_types)) + 26 * len(widgets_values) + TEXT_BOX_HEIGHT * text_boxes],
            "flags": {},
            "order": order,
            "mode": 0,
            "inputs": inputs,
            "outputs": [{"name": output_names[i], "type": t, "links": [], "slot_index": i} for i, t in enumerate(output_types)],
            "properties": {"Node name for S&R": api_node["class_type"]},
            "widgets_values": widgets_values,
        }

    for node_id, api_node in prompt.items():
        target = nodes[node_id]
        for slot, socket in enumerate(target["inputs"]):
            value = api_node["inputs"].get(socket["name"])
            if not is_link(value):
                continue
            source = nodes[str(value[0])]
            link_id = len(links) + 1
            links.append([link_id, source["id"], value[1], target["id"], slot, socket["type"]])
            socket["link"] = link_id
            source["outputs"][value[1]]["links"].append(link_id)

    column_y = {}
    for node_id, depth in _depths(prompt).items():
        y = column_y.get(depth, 50)
        nodes[node_id]["pos"] = [50 + depth * COLUMN_WIDTH, y]
        column_y[depth] = y + nodes[node_id]["size"][1] + 60

    return {
        "last_node_id": max(ids.values(), default=0),
        "last_link_id": len(links),
        "nodes": list(nodes.values()),
        "links": links,
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


def display_risks(prompt, object_info):
    """Node types whose widgets the frontend builds itself, so the canvas may show their values out of place."""
    risky = set()
    for api_node in prompt.values():
        for _, spec in _ordered_inputs(object_info[api_node["class_type"]]):
            extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if (isinstance(spec[0], str) and spec[0] in FRONTEND_DRIVEN_TYPES) or "widgetType" in extra:
                risky.add(api_node["class_type"])
    return sorted(risky)


def _signature(ui):
    """What a canvas edit would change; node positions and sizes are left out."""
    nodes = sorted([n["id"], n["type"], n.get("mode", 0), n.get("widgets_values")] for n in ui["nodes"])
    links = sorted(
        [l["origin_id"], l["origin_slot"], l["target_id"], l["target_slot"]] if isinstance(l, dict) else list(l[1:5])
        for l in ui.get("links", [])
    )
    return {"nodes": nodes, "links": links}


def attach_prompt(ui, prompt):
    ui = copy.deepcopy(ui)
    ui["extra"]["comfypilot"] = {"prompt": copy.deepcopy(prompt), "signature": copy.deepcopy(_signature(ui))}
    return ui


def embedded_prompt(ui):
    """The API prompt ComfyPilot saved with this canvas file, or None if it has none."""
    saved = ui.get("extra", {}).get("comfypilot")
    if not saved:
        return None
    if _signature(ui) != saved["signature"]:
        raise WorkflowError("This workflow was edited in ComfyUI after ComfyPilot saved it. Export it with Save (API Format), or save it again with save_workflow.")
    return saved["prompt"]
