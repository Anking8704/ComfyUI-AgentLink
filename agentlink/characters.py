"""Validated, atomic local character records. Never opens model weights or downloads models."""
import json
import math
import os
import tempfile
import threading
from pathlib import Path

from .errors import ToolError

MAX_STORAGE_BYTES = 2 * 2**20
MAX_SIDECAR_BYTES = 64 * 2**10
MAX_RECORDS = 2000
FIELDS = {"character", "model_path", "aliases", "trigger_words", "appearance_prompt",
          "strength_model", "strength_clip", "base_model", "provenance"}
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _text(value, field, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ToolError(f"{field} must be nonempty text (max {limit} characters)")
    return value


def _model_key(value):
    _text(value, "model_path", 1024)
    normalized = value.replace("\\", "/")
    if any(ord(c) < 32 for c in value) or ":" in value or normalized.startswith("/") or any(part in ("", ".", "..") for part in normalized.split("/")):
        raise ToolError("model_path must be an exact installed relative LoRA path; absolute paths and traversal are forbidden")
    return normalized


def _strings(value, field):
    if not isinstance(value, list) or len(value) > 100:
        raise ToolError(f"{field} must be a list of at most 100 strings")
    result = []
    for item in value:
        item = _text(item, field, 512)
        if item not in result:
            result.append(item)
    return result


def _record(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ToolError(f"record must be an object with fields: {', '.join(sorted(FIELDS))}")
    result = {"character": _text(value.get("character"), "character"),
              "model_path": value.get("model_path"), "aliases": _strings(value.get("aliases", []), "aliases")}
    _model_key(result["model_path"])
    triggers = value.get("trigger_words")
    result["trigger_words"] = None if triggers is None else _strings(triggers, "trigger_words")
    for field, limit in (("appearance_prompt", 8192), ("base_model", 256), ("provenance", 2048)):
        item = value.get(field)
        result[field] = item if item is None or (field == "appearance_prompt" and item == "") else _text(item, field, limit)
    for field in ("strength_model", "strength_clip"):
        number = value.get(field)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or not -100 <= number <= 100):
            raise ToolError(f"{field} must be a finite number between -100 and 100, or null for unknown")
        result[field] = number
    return result


def _identity(record):
    return record["character"].casefold(), _model_key(record["model_path"])


def _installed(files):
    if not isinstance(files, list):
        raise ToolError("Installed LoRA listing must be a list")
    result = {}
    for name in files:
        try:
            result[_model_key(name)] = name
        except ToolError:
            continue
    return result


def _limit(limit):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ToolError("limit must be an integer between 1 and 200")
    return limit


class CharacterStore:
    def __init__(self, path, resolve_model=None):
        self.path = Path(path)
        # Only the host supplies this trusted registry resolver; never a tool argument.
        self.resolve_model = resolve_model
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.path.resolve())), threading.RLock())

    def _load(self):
        try:
            with self.path.open("rb") as source:
                raw = source.read(MAX_STORAGE_BYTES + 1)
        except FileNotFoundError:
            return []
        except OSError as e:
            raise ToolError(f"Cannot read character storage: {e}") from e
        try:
            if len(raw) > MAX_STORAGE_BYTES:
                raise ValueError("file exceeds 2 MiB")
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {"version", "characters"} or type(data["version"]) is not int or data["version"] != 1:
                raise ValueError("unsupported file format")
            if not isinstance(data["characters"], list) or len(data["characters"]) > MAX_RECORDS:
                raise ValueError("invalid record list")
            records = [_record(item) for item in data["characters"]]
            if len({_identity(item) for item in records}) != len(records):
                raise ValueError("duplicate character/model identity")
            return records
        except (ValueError, TypeError, ToolError) as e:
            raise ToolError(f"Invalid character storage; repair or restore characters.json before saving (file left intact): {e}") from e

    def list(self, query="", limit=50):
        _limit(limit)
        if not isinstance(query, str) or len(query) > 512:
            raise ToolError("query must be text (max 512 characters)")
        query = query.casefold()
        path_query = query.replace("\\", "/")
        with self._lock:
            records = self._load()
        return [r for r in records if not query or path_query in _model_key(r["model_path"]).casefold()
                or any(query in text.casefold() for text in [r["character"], *r["aliases"]])][:limit]

    def read(self, character, model_path=""):
        _text(character, "character")
        model_key = _model_key(model_path) if model_path else None
        with self._lock:
            matches = [r for r in self._load() if character.casefold() in [s.casefold() for s in [r["character"], *r["aliases"]]]
                       and (model_key is None or _model_key(r["model_path"]) == model_key)]
        if not matches:
            raise ToolError("No saved character matches. Use search_character_loras to discover installed candidates.")
        if len(matches) != 1:
            raise ToolError("Ambiguous character/version. Choose an exact model_path from: " + ", ".join(r["model_path"] for r in matches))
        return matches[0]

    def save(self, record, installed):
        # Validate supplied fields before reading/updating existing records.
        validated = _record(record)
        models = _installed(installed)
        key = _model_key(validated["model_path"])
        if key not in models:
            raise ToolError("model_path is not an exact installed LoRA path. Use search_character_loras or list_models(folder='loras').")
        with self._lock:
            records = self._load()
            index = next((i for i, item in enumerate(records) if _identity(item) == _identity(validated)), None)
            saved = _record({**(records[index] if index is not None else {}), **record, "model_path": models[key]})
            if index is None:
                if len(records) >= MAX_RECORDS:
                    raise ToolError("Character storage is full (2000 records)")
                records.append(saved)
            else:
                records[index] = saved
            self._write(records)
        return saved

    def _write(self, records):
        temporary = None
        try:
            content = json.dumps({"version": 1, "characters": records}, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            if len(content) > MAX_STORAGE_BYTES:
                raise ToolError("Character storage would exceed 2 MiB")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent, prefix=".characters-", suffix=".tmp", delete=False) as target:
                temporary = Path(target.name)
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
        except (OSError, UnicodeError, ValueError) as e:
            raise ToolError(f"Cannot save character storage; previous records preserved: {e}") from e
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _metadata(self, name):
        if self.resolve_model is None:
            return {}
        try:
            resolved = self.resolve_model(name)
            if not resolved:
                return {}
            model = Path(resolved).resolve()
            sidecar = model.with_suffix(".json")
            if sidecar.resolve().parent != model.parent:
                raise ValueError("sidecar points outside the model directory")
            try:
                with sidecar.open("rb") as source:
                    raw = source.read(MAX_SIDECAR_BYTES + 1)
            except FileNotFoundError:
                return {}
            if len(raw) > MAX_SIDECAR_BYTES:
                raise ValueError("sidecar exceeds 64 KiB")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("sidecar must be a JSON object")
            words = data.get("trigger_words", data.get("trainedWords"))
            base = data.get("base_model", data.get("baseModel"))
            # ss_tag_frequency and other training statistics are deliberately ignored.
            return {"metadata": {"trigger_words": _strings(words, "trigger_words") if words is not None else None,
                                 "base_model": _text(base, "base_model") if base is not None else None,
                                 "provenance": "local JSON sidecar: " + sidecar.name}}
        except (OSError, ValueError, ToolError) as e:
            return {"metadata_warning": f"Local sidecar ignored: {e}"}

    def search(self, query, installed, limit=50):
        _text(query, "query", 512)
        _limit(limit)
        needle = query.casefold()
        path_needle = needle.replace("\\", "/")
        models = _installed(installed)
        candidates = []
        with self._lock:
            records = self._load()
        represented = set()
        for record in records:
            key = _model_key(record["model_path"])
            represented.add(key)
            if needle == record["character"].casefold():
                rank, match = 0, "character"
            elif needle in [a.casefold() for a in record["aliases"]]:
                rank, match = 0, "alias"
            elif path_needle in (key.casefold(), Path(key).name.casefold(), Path(key).stem.casefold()):
                rank, match = 1, "filename"
            elif path_needle in key.casefold() or any(needle in s.casefold() for s in [record["character"], *record["aliases"]]):
                rank, match = 2, "partial"
            else:
                continue
            candidates.append({"model_path": models.get(key, record["model_path"]), "record": record,
                               "installed": key in models, "match": match, "rank": rank})
        for key, name in models.items():
            if key not in represented and path_needle in key.casefold():
                rank = 1 if path_needle in (key.casefold(), Path(key).name.casefold(), Path(key).stem.casefold()) else 2
                candidates.append({"model_path": name, "record": None, "installed": True, "match": "filename", "rank": rank})
        candidates.sort(key=lambda item: (item["rank"], item["model_path"], (item["record"] or {}).get("character", "")))
        # Never truncate silently into an apparently unique result.
        ambiguous = len(candidates) > 1
        total = len(candidates)
        candidates = candidates[:limit]
        for item in candidates:
            if item["installed"]:
                item.update(self._metadata(item["model_path"]))
        return {"candidates": candidates, "total": total, "ambiguous": ambiguous,
                "note": "Choose an exact character/model version when ambiguous. Unknown triggers or base models must be supplied, never guessed."}
