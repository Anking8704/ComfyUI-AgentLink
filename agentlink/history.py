"""Chat history saved to disk, so a ComfyUI restart does not make the agent forget a conversation the page still shows.

Images are left out (the model already answered about them; the page keeps its own thumbnails), long histories are cut at
a user message so tool calls always keep their results, and only the most recent chats are kept.
"""
import json
import os
import re
import tempfile
import time

_SESSION = re.compile(r"[0-9a-f]{8,64}")
MAX_MESSAGES = 120
MAX_FILES = 40


def _without_images(message):
    message = dict(message)
    if message.get("images"):
        message["text"] = f"{message.get('text', '')}\n[{len(message['images'])} reference image(s) were attached here]".strip()
        message.pop("images")
    if isinstance(message.get("content"), list):
        message["content"] = [block if block.get("type") != "image" else {"type": "text", "text": "[image shown to the model here]"}
                              for block in message["content"]]
    return message


def trimmed(history, limit=MAX_MESSAGES):
    """The last `limit` messages, starting at a user message so no tool result loses its call."""
    if len(history) <= limit:
        return list(history)
    for start in range(len(history) - limit, len(history)):
        if history[start].get("role") == "user":
            return list(history[start:])
    # One very long turn: keep it whole rather than lose the conversation.
    for start in range(len(history) - 1, -1, -1):
        if history[start].get("role") == "user":
            return list(history[start:])
    return []


class HistoryStore:
    def __init__(self, folder):
        self.folder = folder

    def _path(self, session):
        return os.path.join(self.folder, f"{session}.json") if _SESSION.fullmatch(session or "") else None

    def load(self, session):
        path = self._path(session)
        if not path:
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        messages = data.get("history") if isinstance(data, dict) else None
        return [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant", "tool")] if isinstance(messages, list) else []

    def save(self, session, history):
        """Best effort: a failure to save never breaks the chat itself."""
        path = self._path(session)
        if not path:
            return
        temp = None
        try:
            os.makedirs(self.folder, exist_ok=True)
            data = {"saved": int(time.time()), "history": [_without_images(m) for m in trimmed(history)]}
            fd, temp = tempfile.mkstemp(dir=self.folder, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            os.replace(temp, path)
            temp = None
            self._prune()
        except Exception:  # noqa: BLE001
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    pass

    def delete(self, session):
        path = self._path(session)
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _prune(self):
        try:
            files = [os.path.join(self.folder, n) for n in os.listdir(self.folder) if n.endswith(".json")]
        except OSError:
            return
        def modified(p):
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0
        files.sort(key=modified, reverse=True)
        for old in files[MAX_FILES:]:
            try:
                os.unlink(old)
            except OSError:
                pass
