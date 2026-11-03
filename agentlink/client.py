import json
from urllib.parse import quote

import aiohttp

from .errors import ToolError

CLIENT_ID = "agentlink"


class ComfyError(ToolError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class ComfyOffline(ComfyError):
    pass


class ComfyClient:
    """Talks to the ComfyUI HTTP API, normally the server this extension is running in."""

    def __init__(self, base_url, ssl=None):
        self.base_url = base_url
        self._ssl = ssl
        self._session = None

    def _http(self):
        if self._session is None or self._session.closed:
            # trust_env=False: a system proxy must not intercept calls back into ComfyUI.
            self._session = aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=120))
        return self._session

    async def close(self):
        if self._session is not None:
            await self._session.close()

    async def _request(self, method, path, **kwargs):
        try:
            async with self._http().request(method, self.base_url + path, ssl=self._ssl, **kwargs) as response:
                body = await response.read()
                if response.status >= 400:
                    text = body.decode("utf-8", "replace")[:500]
                    raise ComfyError(f"{method} {path} failed with HTTP {response.status}: {text}", response.status)
                return body
        except aiohttp.ClientConnectionError as e:
            raise ComfyOffline(f"ComfyUI is not reachable at {self.base_url}: {e}") from e

    async def get_json(self, path, **params):
        return json.loads(await self._request("GET", path, params=params))

    async def post(self, path, body=None):
        content = await self._request("POST", path, json=body)
        return json.loads(content) if content else None

    async def get_workflow(self, name):
        return json.loads(await self._request("GET", "/userdata/" + quote(f"workflows/{name}", safe="")))

    async def save_workflow(self, name, workflow, overwrite):
        content = json.dumps(workflow, ensure_ascii=False, indent=2).encode("utf-8")
        params = {"overwrite": "true" if overwrite else "false"}
        await self._request("POST", "/userdata/" + quote(f"workflows/{name}", safe=""), params=params, data=content)

    async def get_view(self, filename, subfolder, file_type):
        return await self._request("GET", "/view", params={"filename": filename, "subfolder": subfolder, "type": file_type})

    async def upload_image(self, name, content):
        form = aiohttp.FormData()
        form.add_field("image", content, filename=name)
        form.add_field("type", "input")
        return json.loads(await self._request("POST", "/upload/image", data=form))

    async def submit_prompt(self, prompt, prompt_id):
        """Never retried: a lost response does not mean the job was not queued."""
        body = {"prompt": prompt, "prompt_id": prompt_id, "client_id": CLIENT_ID}
        try:
            async with self._http().post(self.base_url + "/prompt", json=body, ssl=self._ssl) as response:
                text = await response.text()
                status = response.status
        except aiohttp.ClientError as e:
            raise ComfyError(f"Lost contact while submitting; job {prompt_id} may be queued. Check get_job before resubmitting. ({e})") from e
        if status == 400:
            raise ComfyError(_describe_rejection(json.loads(text)), status)
        if status >= 400:
            raise ComfyError(f"POST /prompt failed with HTTP {status}: {text[:500]}", status)
        return json.loads(text)


def _describe_rejection(body):
    error = body.get("error", {})
    lines = [error.get("message", "ComfyUI rejected the workflow") if isinstance(error, dict) else str(error)]
    for node_id, node in body.get("node_errors", {}).items():
        for item in node.get("errors", []):
            lines.append(f"{node_id} ({node.get('class_type')}): {item.get('message')} {item.get('details', '')}".rstrip())
    return "\n".join(lines)
