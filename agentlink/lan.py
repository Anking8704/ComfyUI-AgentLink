"""Phone access: phones on the same network pair once with a short code shown on the computer.

A code works once, for ten minutes, and burns after a few wrong guesses. Pairing hands the phone a long random
token kept in a cookie; only its hash is stored. Turning phone access off locks every phone out until it is on again.
"""
import hashlib
import hmac
import json
import os
import secrets
import socket
import time


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def lan_addresses():
    """This computer's IPv4 addresses a phone on the same network could reach."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos if not info[4][0].startswith(("127.", "169.254.", "198.18.", "198.19."))})


class LanAccess:
    COOKIE = "agentlink_device"
    CODE_SECONDS = 600
    MAX_TRIES = 5

    def __init__(self, path):
        self.path = path
        self._code = None
        self._expires = 0.0
        self._tries = 0

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        return {"enabled": bool(data.get("enabled")), "devices": list(data.get("devices") or [])}

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _live_code(self):
        if self._code and time.monotonic() < self._expires and self._tries < self.MAX_TRIES:
            return self._code
        self._code = None
        return None

    def view(self):
        data = self._load()
        code = self._live_code() if data["enabled"] else None
        return {"enabled": data["enabled"], "code": code, "expires_in": max(0, int(self._expires - time.monotonic())) if code else 0,
                "devices": len(data["devices"]), "addresses": lan_addresses()}

    def new_code(self):
        self._code = f"{secrets.randbelow(10**6):06d}"
        self._expires = time.monotonic() + self.CODE_SECONDS
        self._tries = 0
        return self.view()

    def set_enabled(self, enabled):
        data = self._load()
        data["enabled"] = bool(enabled)
        self._save(data)
        if enabled:
            return self.new_code()
        self._code = None
        return self.view()

    def revoke_all(self):
        data = self._load()
        data["devices"] = []
        self._save(data)
        return self.view()

    def pair(self, code):
        """A device token for a correct code, or None."""
        data = self._load()
        live = self._live_code() if data["enabled"] else None
        if live is None:
            return None
        code = str(code).strip()
        if not code.isascii() or not hmac.compare_digest(code, live):
            self._tries += 1
            return None
        self._code = None
        token = secrets.token_urlsafe(32)
        data["devices"].append({"hash": _hash(token), "paired_at": int(time.time())})
        self._save(data)
        return token

    def is_paired(self, token):
        if not token:
            return False
        data = self._load()
        digest = _hash(token)
        return data["enabled"] and any(hmac.compare_digest(d.get("hash", ""), digest) for d in data["devices"])
