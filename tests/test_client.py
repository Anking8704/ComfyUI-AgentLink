import pytest

from agentlink.client import ComfyClient, ComfyError, ComfyOffline


async def test_connection_failure_reports_offline():
    client = ComfyClient("http://127.0.0.1:9")
    with pytest.raises(ComfyOffline, match="127.0.0.1:9"):
        await client.get_json("/queue")
    await client.close()


async def test_http_error_carries_status(client):
    with pytest.raises(ComfyError, match="404") as raised:
        await client.get_json("/models/nope")
    assert raised.value.status == 404


async def test_lost_response_on_submit_says_outcome_is_unknown_and_does_not_retry(client, comfy):
    comfy.drop_prompt_connection = True
    with pytest.raises(ComfyError, match="abc") as raised:
        await client.submit_prompt({"1": {}}, "abc")
    assert "may" in str(raised.value)
    assert len(comfy.posts) == 1


async def test_workflow_names_with_slashes_and_spaces_round_trip(client, comfy):
    assert await client.get_workflow("sub/ui file.json") == comfy.workflows["sub/ui file.json"]
