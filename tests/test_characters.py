"""Local character memory: exact identity, safe storage, explicit metadata only."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from agentlink.errors import ToolError


def store_at(tmp_path, **kwargs):
    from agentlink.characters import CharacterStore
    return CharacterStore(tmp_path / "agentlink" / "characters.json", **kwargs)


MODELS = ["series/Hero-v1.safetensors", "series/Hero-v2.safetensors", "other/Hero-v1.safetensors"]


def hero(**extra):
    return {"character": "Hero", "model_path": MODELS[0], "aliases": ["勇者"],
            "trigger_words": ["hero_token"], **extra}


def test_persists_restart_and_partial_updates_without_losing_zero_or_triggers(tmp_path):
    store = store_at(tmp_path)
    store.save(hero(strength_model=0, strength_clip=0, appearance_prompt="silver hair"), MODELS)
    fresh = store_at(tmp_path)
    fresh.save({"character": "Hero", "model_path": MODELS[0], "base_model": "SDXL"}, MODELS)
    result = store_at(tmp_path).read("勇者")
    assert result["trigger_words"] == ["hero_token"]
    assert result["strength_model"] == result["strength_clip"] == 0
    assert result["appearance_prompt"] == "silver hair"
    assert result["base_model"] == "SDXL"


def test_alias_ranks_above_filename_and_versions_stay_ambiguous(tmp_path):
    store = store_at(tmp_path)
    store.save(hero(aliases=["Hero-v2"]), MODELS)
    store.save(hero(model_path=MODELS[1]), MODELS)
    found = store.search("Hero-v2", MODELS)
    assert found["candidates"][0]["model_path"] == MODELS[0]
    assert found["candidates"][0]["match"] == "alias"
    with pytest.raises(ToolError, match="[Aa]mbiguous"):
        store.read("Hero")
    assert store.read("Hero", MODELS[1])["model_path"] == MODELS[1]
    assert len(store.list()) == 2


def test_same_basename_requires_exact_path_and_unknown_triggers_remain_unknown(tmp_path):
    store = store_at(tmp_path)
    with pytest.raises(ToolError, match="installed"):
        store.save(hero(model_path="Hero-v1.safetensors"), MODELS)
    saved = store.save({"character": "Other", "model_path": MODELS[2]}, MODELS)
    assert saved["trigger_words"] is None
    assert saved["base_model"] is None
    assert store.search("Hero-v1", MODELS)["ambiguous"] is True
    assert {r["model_path"] for r in store.search("Hero-v1", MODELS)["candidates"]} == {MODELS[0], MODELS[2]}


def test_windows_registry_spelling_is_preserved_and_both_slashes_search_saved_and_unsaved(tmp_path):
    store = store_at(tmp_path)
    installed = [r"series\Hero-v1.safetensors"]
    assert store.search(installed[0], installed)["candidates"][0]["model_path"] == installed[0]
    saved = store.save(hero(model_path=MODELS[0], trigger_words=[]), installed)
    assert saved["model_path"] == installed[0]
    assert saved["trigger_words"] == []
    for query in (installed[0], MODELS[0]):
        assert store.search(query, installed)["candidates"][0]["record"]["model_path"] == installed[0]
        assert store.list(query)[0]["model_path"] == installed[0]


def test_empty_appearance_prompt_can_clear_saved_prompt(tmp_path):
    store = store_at(tmp_path)
    store.save(hero(appearance_prompt="silver hair"), MODELS)
    store.save({"character": "Hero", "model_path": MODELS[0], "appearance_prompt": ""}, MODELS)
    assert store.read("Hero")["appearance_prompt"] == ""


@pytest.mark.parametrize("bad", [
    {"model_path": "../secret"}, {"model_path": "C:\\secret"}, {"model_path": "/secret"},
    {"model_path": "a/../secret"}, {"model_path": "\\\\host\\file"},
    {"model_path": "a\x00.safetensors"}, {"character": ""}, {"character": 1},
    {"aliases": "nickname"}, {"aliases": [1]}, {"trigger_words": "tag"},
    {"trigger_words": [""]}, {"strength_model": True}, {"strength_clip": float("nan")},
    {"strength_model": float("inf")}, {"appearance_prompt": 1}, {"unknown_field": "x"},
])
def test_rejects_malformed_records_without_writing(tmp_path, bad):
    store = store_at(tmp_path)
    with pytest.raises(ToolError):
        store.save(hero(**bad), MODELS)
    assert not store.path.exists()


@pytest.mark.parametrize("contents", ["{broken", '{"version": 99, "characters": []}',
    '{"version": 1, "characters": [{"character": "x", "model_path": "../bad"}]}'])
def test_corrupt_storage_is_reported_and_never_overwritten(tmp_path, contents):
    store = store_at(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(contents, encoding="utf-8")
    with pytest.raises(ToolError, match="storage"):
        store.list()
    with pytest.raises(ToolError, match="storage"):
        store.save(hero(), MODELS)
    assert store.path.read_text(encoding="utf-8") == contents


def test_atomic_failure_keeps_old_records_and_cleans_temporary_file(tmp_path):
    store = store_at(tmp_path)
    store.save(hero(), MODELS)
    before = store.path.read_bytes()
    with patch("agentlink.characters.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(ToolError, match="disk full"):
            store.save(hero(trigger_words=["changed"]), MODELS)
    assert store.path.read_bytes() == before
    assert list(store.path.parent.iterdir()) == [store.path]


def test_safe_sidecar_uses_only_explicit_metadata_never_training_frequency(tmp_path):
    model = tmp_path / "models" / "Hero.safetensors"
    model.parent.mkdir()
    model.write_bytes(b"weights are never read")
    sidecar = model.with_suffix(".json")
    sidecar.write_text(json.dumps({"trainedWords": ["hero", "hero"], "baseModel": "SDXL", "ss_tag_frequency": {"invented": 999}}))
    store = store_at(tmp_path, resolve_model=lambda name: model)
    found = store.search("Hero", ["Hero.safetensors"])["candidates"][0]
    assert found["metadata"]["trigger_words"] == ["hero"]
    assert found["metadata"]["base_model"] == "SDXL"
    assert not store.path.exists()
    sidecar.write_text(json.dumps({"ss_tag_frequency": {"invented": 999}}))
    assert store.search("Hero", ["Hero.safetensors"])["candidates"][0]["metadata"]["trigger_words"] is None
    sidecar.write_text("x" * 70000)
    assert "metadata_warning" in store.search("Hero", ["Hero.safetensors"])["candidates"][0]


def test_removed_model_is_reported_and_unsafe_registry_entry_is_ignored(tmp_path):
    store = store_at(tmp_path)
    store.save(hero(), MODELS)
    found = store.search("Hero", ["../Hero.safetensors"])
    assert len(found["candidates"]) == 1
    assert found["candidates"][0]["installed"] is False


def test_limit_does_not_hide_ambiguity(tmp_path):
    found = store_at(tmp_path).search("Hero", MODELS, limit=1)
    assert len(found["candidates"]) == 1
    assert found["total"] == 3 and found["ambiguous"] is True


def test_sidecar_symlink_outside_model_directory_is_never_read(tmp_path, monkeypatch):
    model = tmp_path / "models" / "Hero.safetensors"
    model.parent.mkdir()
    secret = tmp_path / "private.json"
    secret.write_text('{"trainedWords": ["must_not_read"]}')
    try:
        model.with_suffix(".json").symlink_to(secret)
    except OSError:
        # Windows without the symlink privilege: exercise the same resolved-path boundary.
        resolve = Path.resolve
        sidecar = model.with_suffix(".json")
        monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                            secret if path == sidecar else resolve(path, *args, **kwargs))
    store = store_at(tmp_path, resolve_model=lambda name: model)
    result = store.search("Hero", ["Hero.safetensors"])["candidates"][0]
    assert "outside" in result["metadata_warning"]
    assert "metadata" not in result


def test_store_instances_serialize_reload_and_write_without_lost_updates(tmp_path):
    first, second = store_at(tmp_path), store_at(tmp_path)
    writing, release, second_finished = threading.Event(), threading.Event(), threading.Event()
    write = first._write

    def paused_write(records):
        writing.set()
        assert release.wait(5)
        write(records)

    def save_second():
        try:
            second.save(hero(model_path=MODELS[1]), MODELS)
        finally:
            second_finished.set()

    first._write = paused_write
    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(first.save, hero(), MODELS)
        assert writing.wait(5)
        two = pool.submit(save_second)
        try:
            assert not second_finished.wait(0.1), "second writer bypassed the shared storage lock"
        finally:
            release.set()
        one.result()
        two.result()
    assert {r["model_path"] for r in store_at(tmp_path).list()} == {MODELS[0], MODELS[1]}


async def test_character_tools_use_http_registry_and_unconfigured_store_cannot_write(client, comfy, tmp_path):
    from agentlink.tools import Toolset
    comfy.model_files["loras"] = MODELS
    tools = Toolset(client, characters=store_at(tmp_path))
    saved = await tools.call("save_character", {"record": hero(strength_model=0)})
    assert not saved.is_error, saved.content
    found = await tools.call("search_character_loras", {"query": "勇者"})
    assert found.structured["candidates"][0]["record"]["strength_model"] == 0
    read = await tools.call("read_character", {"character": "Hero", "model_path": MODELS[0]})
    assert read.structured["trigger_words"] == ["hero_token"]
    assert (await tools.call("list_characters", {})).structured["records"][0]["character"] == "Hero"
    denied = await Toolset(client).call("save_character", {"record": hero()})
    assert denied.is_error and "configured" in denied.content[0]["text"]
