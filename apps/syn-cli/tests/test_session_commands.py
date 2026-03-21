"""Tests for session CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()


def _mock_response(status_code: int = 200, json_data: dict | list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _mock_client(*responses: MagicMock) -> MagicMock:
    client = MagicMock()
    all_responses = list(responses)
    call_idx = {"i": 0}

    def _next_response(*_args: object, **_kwargs: object) -> MagicMock:
        idx = call_idx["i"]
        call_idx["i"] += 1
        return all_responses[idx] if idx < len(all_responses) else _mock_response()

    client.get.side_effect = _next_response
    client.post.side_effect = _next_response
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


@pytest.mark.unit
class TestSessionList:
    def test_list_sessions(self) -> None:
        data = [
            {
                "id": "sess-1234567890ab",
                "status": "completed",
                "agent_provider": "claude",
                "total_tokens": 5000,
                "total_cost_usd": "0.25",
                "started_at": "2026-03-16T14:00:00+00:00",
            },
        ]
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.sessions.get_client", return_value=client):
            result = runner.invoke(app, ["sessions", "list"])
        assert result.exit_code == 0
        assert "sess-123456" in result.stdout
        assert "claude" in result.stdout

    def test_list_sessions_empty(self) -> None:
        client = _mock_client(_mock_response(200, []))
        with patch("syn_cli.commands.sessions.get_client", return_value=client):
            result = runner.invoke(app, ["sessions", "list"])
        assert result.exit_code == 0
        assert "No sessions found" in result.stdout

    def test_list_sessions_connection_error(self) -> None:
        with patch("syn_cli.commands.sessions.get_client", side_effect=Exception("conn")):
            result = runner.invoke(app, ["sessions", "list"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout


@pytest.mark.unit
class TestSessionShow:
    def test_show_session(self) -> None:
        data = {
            "id": "sess-abc",
            "status": "completed",
            "agent_provider": "claude",
            "agent_model": "claude-sonnet-4-5",
            "workflow_name": "Test Workflow",
            "input_tokens": 3000,
            "output_tokens": 2000,
            "total_tokens": 5000,
            "total_cost_usd": "0.50",
            "started_at": "2026-03-16T14:00:00+00:00",
            "operations": [
                {
                    "operation_id": "op-1",
                    "operation_type": "tool_use",
                    "tool_name": "read_file",
                    "duration_seconds": 1.5,
                    "success": True,
                },
            ],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.sessions.get_client", return_value=client):
            result = runner.invoke(app, ["sessions", "show", "sess-abc"])
        assert result.exit_code == 0
        assert "Test Workflow" in result.stdout
        assert "read_file" in result.stdout

    def test_show_session_not_found(self) -> None:
        client = _mock_client(_mock_response(404, {"detail": "Session not found"}))
        with patch("syn_cli.commands.sessions.get_client", return_value=client):
            result = runner.invoke(app, ["sessions", "show", "bad-id"])
        assert result.exit_code == 1
        assert "Session not found" in result.stdout

    def test_show_session_with_error(self) -> None:
        data = {
            "id": "sess-err",
            "status": "failed",
            "total_tokens": 0,
            "total_cost_usd": "0",
            "error_message": "Agent crashed",
            "operations": [],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.sessions.get_client", return_value=client):
            result = runner.invoke(app, ["sessions", "show", "sess-err"])
        assert result.exit_code == 0
        assert "Agent crashed" in result.stdout
