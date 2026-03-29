"""Tests for artifact CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()

_HELPERS_CLIENT = "syn_cli.commands._api_helpers.get_client"


def _mock_response(
    status_code: int = 200, json_data: dict | list | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _mock_client(*responses: MagicMock) -> MagicMock:
    """Create a mock httpx.Client context manager returning sequential responses."""
    client = MagicMock()
    all_responses = list(responses)
    call_idx = {"i": 0}

    def _next_response(*_args: object, **_kwargs: object) -> MagicMock:
        idx = call_idx["i"]
        call_idx["i"] += 1
        return all_responses[idx] if idx < len(all_responses) else _mock_response()

    client.get.side_effect = _next_response
    client.post.side_effect = _next_response
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


@pytest.mark.unit
class TestArtifactCreate:
    def test_create_success(self) -> None:
        client = _mock_client(
            _mock_response(200, {"id": "art-new-id", "status": "created"})
        )
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                [
                    "artifacts",
                    "create",
                    "--workflow",
                    "wf-123",
                    "--type",
                    "document",
                    "--title",
                    "Test Doc",
                    "--content",
                    "Hello world",
                ],
            )
        assert result.exit_code == 0
        assert "Test Doc" in result.stdout

    def test_create_help(self) -> None:
        result = runner.invoke(app, ["artifacts", "create", "--help"])
        assert result.exit_code == 0
        assert "--workflow" in result.stdout
        assert "--type" in result.stdout
        assert "--title" in result.stdout
        assert "--content" in result.stdout


@pytest.mark.unit
class TestArtifactList:
    def test_list_empty(self) -> None:
        client = _mock_client(_mock_response(200, []))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["artifacts", "list"])
        assert result.exit_code == 0
        assert "No artifacts found" in result.stdout

    def test_list_with_results(self) -> None:
        artifacts = [
            {
                "id": "art-123-abc",
                "artifact_type": "document",
                "title": "Test Artifact",
                "size_bytes": 1024,
                "created_at": "2025-01-01T00:00:00",
            }
        ]
        client = _mock_client(_mock_response(200, artifacts))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["artifacts", "list"])
        assert result.exit_code == 0
        assert "Test Artifact" in result.stdout
