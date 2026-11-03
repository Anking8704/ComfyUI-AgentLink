"""A scripted OpenAI-compatible model on 127.0.0.1:8765 that drives AgentLink through one turn on the open canvas:
read_canvas, edit_canvas (prompt and steps), run_canvas, get_job, then a reply. For manual browser checks only."""
import json

from aiohttp import web


def tool_results(messages):
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


def plan(messages):
    step = sum(1 for m in messages if m["role"] == "assistant")
    results = tool_results(messages)
    if step == 0:
        return "我先看看你画布上的工作流。", ("read_canvas", {})
    if step == 1:
        nodes = results[-1]["nodes"]
        text_node = next(n for n in nodes if "text" in n["values"])
        changes = {f"{text_node['id']}.text": "masterpiece, best quality, a cat sitting on a beach at sunset, scenery"}
        sampler = next((n for n in nodes if "steps" in n["values"]), None)
        if sampler:
            changes[f"{sampler['id']}.steps"] = 8
        return "", ("edit_canvas", {"changes": changes})
    if step == 2:
        return "提示词和步数改好了，开始生成。", ("run_canvas", {})
    if step == 3:
        return "", ("get_job", {"prompt_id": results[-1]["prompt_ids"][0], "wait_seconds": 200})
    return "画好了：用你当前的工作流，只改了正面提示词和步数。", None


async def chat(request):
    body = await request.json()
    if "tools" not in body:
        return web.json_response({"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})
    text, call = plan(body["messages"])
    message = {"content": text or None}
    if call:
        step = sum(1 for m in body["messages"] if m["role"] == "assistant")
        message["tool_calls"] = [{"id": f"call_{step}", "type": "function", "function": {"name": call[0], "arguments": json.dumps(call[1], ensure_ascii=False)}}]
    return web.json_response({"choices": [{"message": message, "finish_reason": "tool_calls" if call else "stop"}]})


app = web.Application(client_max_size=64 * 2**20)
app.router.add_post("/v1/chat/completions", chat)
web.run_app(app, host="127.0.0.1", port=8765)
