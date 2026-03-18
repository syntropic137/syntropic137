"""Tests for observability CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
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
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


@pytest.mark.unit
class TestObserveTools:
    def test_tool_timeline(self) -> None:
        data = {
            "session_id": "sess-abc",
            "total_executions": 3,
            "executions": [
                {
                    "tool_name": "read_file",
                    "operation_type": "tool_use",
                    "duration_ms": 1500,
                    "success": True,
                },
                {
                    "tool_name": "write_file",
                    "operation_type": "tool_use",
                    "duration_ms": 2000,
                    "success": True,
                },
                {
                    "tool_name": "bash",
                    "operation_type": "tool_use",
                    "duration_ms": 500,
                    "success": False,
                },
            ],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.observe.get_client", return_value=client):
            result = runner.invoke(app, ["observe", "tools", "sess-abc"])
        assert result.exit_code == 0
        assert "read_file" in result.stdout
        assert "write_file" in result.stdout
        assert "bash" in result.stdout

    def test_tool_timeline_empty(self) -> None:
        data = {"session_id": "sess-abc", "total_executions": 0, "executions": []}
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.observe.get_client", return_value=client):
            result = runner.invoke(app, ["observe", "tools", "sess-abc"])
        assert result.exit_code == 0
        assert "No tool executions" in result.stdout

    def test_tool_timeline_not_found(self) -> None:
        client = _mock_client(_mock_response(404, {"detail": "Session not found"}))
        with patch("syn_cli.commands.observe.get_client", return_value=client):
            result = runner.invoke(app, ["observe", "tools", "bad-id"])
        assert result.exit_code == 1
        assert "Session not found" in result.stdout


@pytest.mark.unit
class TestObserveTokens:
    def test_token_metrics(self) -> None:
        data = {
            "session_id": "sess-abc",
            "input_tokens": 5000,
            "output_tokens": 3000,
            "total_tokens": 8000,
            "total_cost_usd": "0.50",
            "cache_creation_tokens": 1000,
            "cache_read_tokens": 2000,
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.observe.get_client", return_value=client):
            result = runner.invoke(app, ["observe", "tokens", "sess-abc"])
        assert result.exit_code == 0
        assert "8.0K" in result.stdout
        assert "$0.50" in result.stdout

    def test_token_metrics_connection_error(self) -> None:
        with patch("syn_cli.commands.observe.get_client", side_effect=Exception("conn")):
            result = runner.invoke(app, ["observe", "tokens", "sess-abc"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout
