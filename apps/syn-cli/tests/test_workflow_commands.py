"""Tests for workflow CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()

_HELPERS_CLIENT = "syn_cli.commands._api_helpers.get_client"
_WORKFLOW_CLIENT = "syn_cli.commands.workflow._run.get_client"


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
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
class TestWorkflowHelp:
    def test_workflow_help(self) -> None:
        result = runner.invoke(app, ["workflow", "--help"])
        assert result.exit_code == 0
        for cmd in ("create", "list", "show", "run", "status", "validate"):
            assert cmd in result.stdout


@pytest.mark.unit
class TestWorkflowList:
    def test_list_empty(self) -> None:
        client = _mock_client(_mock_response(200, {"workflows": []}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "list"])
        assert result.exit_code == 0
        assert "No workflows found" in result.stdout

    def test_list_with_results(self) -> None:
        workflows = [
            {
                "id": "wf-123-abc-def",
                "name": "Test Workflow",
                "workflow_type": "research",
                "phase_count": 3,
            }
        ]
        client = _mock_client(_mock_response(200, {"workflows": workflows}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "list"])
        assert result.exit_code == 0
        assert "Test Workflow" in result.stdout
        assert "research" in result.stdout


@pytest.mark.unit
class TestWorkflowCreate:
    def test_create_success(self) -> None:
        client = _mock_client(_mock_response(200, {"id": "wf-new-id"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                ["workflow", "create", "My Workflow", "--type", "research"],
            )
        assert result.exit_code == 0
        assert "My Workflow" in result.stdout

    def test_create_help(self) -> None:
        result = runner.invoke(app, ["workflow", "create", "--help"])
        assert result.exit_code == 0
        assert "--type" in result.stdout
        assert "--repo" in result.stdout


@pytest.mark.unit
class TestWorkflowValidate:
    def test_validate_help(self) -> None:
        result = runner.invoke(app, ["workflow", "validate", "--help"])
        assert result.exit_code == 0

    def test_validate_valid_file(self) -> None:
        validation = {
            "valid": True,
            "name": "Test",
            "workflow_type": "research",
            "phase_count": 2,
        }
        client = _mock_client(_mock_response(200, validation))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "validate", "/tmp/test.yaml"])
        assert result.exit_code == 0
        assert "Valid" in result.stdout

    def test_validate_invalid_file(self) -> None:
        validation = {
            "valid": False,
            "name": "",
            "workflow_type": "",
            "phase_count": 0,
            "errors": ["Missing required field: name"],
        }
        client = _mock_client(_mock_response(200, validation))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "validate", "/tmp/bad.yaml"])
        assert result.exit_code == 1
        assert "Invalid" in result.stdout


@pytest.mark.unit
class TestWorkflowRun:
    def test_run_not_found(self) -> None:
        client = _mock_client(_mock_response(200, {"workflows": []}))
        with patch(_WORKFLOW_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "run", "nonexistent"])
        assert result.exit_code == 1
        assert "No workflow found" in result.stdout

    def test_run_dry_run(self) -> None:
        workflows = [
            {
                "id": "wf-test-123",
                "name": "Test Workflow",
                "workflow_type": "research",
                "phase_count": 2,
            }
        ]
        client = _mock_client(_mock_response(200, {"workflows": workflows}))
        with patch(_WORKFLOW_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "run", "wf-test-123", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.stdout
