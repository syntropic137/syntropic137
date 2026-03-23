"""Tests for cost CLI commands."""

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
class TestCostSummary:
    def test_summary_displays_totals(self) -> None:
        data = {
            "total_cost_usd": "1.23",
            "total_sessions": 5,
            "total_executions": 2,
            "total_tokens": 50000,
            "total_tool_calls": 100,
            "top_models": [],
            "top_sessions": [],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "summary"])
        assert result.exit_code == 0
        assert "$1.23" in result.stdout
        assert "50.0K" in result.stdout

    def test_summary_with_top_models(self) -> None:
        data = {
            "total_cost_usd": "5.00",
            "total_sessions": 1,
            "total_executions": 1,
            "total_tokens": 1000,
            "total_tool_calls": 10,
            "top_models": [{"model": "claude-sonnet", "cost": "$3.00"}],
            "top_sessions": [],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "summary"])
        assert result.exit_code == 0
        assert "claude-sonnet" in result.stdout

    def test_summary_connection_error(self) -> None:
        with patch("syn_cli.commands._api_helpers.get_client", side_effect=Exception("conn")):
            result = runner.invoke(app, ["costs", "summary"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout


@pytest.mark.unit
class TestCostSessions:
    def test_list_sessions(self) -> None:
        data = [
            {
                "session_id": "sess-1234567890ab",
                "total_cost_usd": "0.50",
                "total_tokens": 10000,
                "duration_ms": 5000,
                "tool_calls": 20,
            },
        ]
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "sessions"])
        assert result.exit_code == 0
        assert "sess-123456" in result.stdout

    def test_list_sessions_empty(self) -> None:
        client = _mock_client(_mock_response(200, []))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "sessions"])
        assert result.exit_code == 0
        assert "No session cost data" in result.stdout


@pytest.mark.unit
class TestCostSessionDetail:
    def test_show_session(self) -> None:
        data = {
            "session_id": "sess-abc",
            "total_cost_usd": "2.50",
            "input_tokens": 5000,
            "output_tokens": 3000,
            "total_tokens": 8000,
            "tool_calls": 15,
            "turns": 3,
            "duration_ms": 30000,
            "started_at": "2026-03-16T14:00:00+00:00",
            "cost_by_model": {"claude-sonnet": "$2.50"},
            "cost_by_tool": {},
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "session", "sess-abc"])
        assert result.exit_code == 0
        assert "$2.50" in result.stdout
        assert "claude-sonnet" in result.stdout

    def test_show_session_not_found(self) -> None:
        client = _mock_client(_mock_response(404, {"detail": "Session not found"}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "session", "bad-id"])
        assert result.exit_code == 1
        assert "Session not found" in result.stdout


@pytest.mark.unit
class TestCostExecutions:
    def test_list_executions(self) -> None:
        data = [
            {
                "execution_id": "exec-1234567890ab",
                "total_cost_usd": "3.00",
                "session_count": 2,
                "total_tokens": 20000,
            },
        ]
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "executions"])
        assert result.exit_code == 0
        assert "exec-123456" in result.stdout


@pytest.mark.unit
class TestCostExecutionDetail:
    def test_show_execution(self) -> None:
        data = {
            "execution_id": "exec-xyz",
            "total_cost_usd": "10.00",
            "session_count": 3,
            "input_tokens": 20000,
            "output_tokens": 10000,
            "total_tokens": 30000,
            "duration_ms": 120000,
            "started_at": "2026-03-16T12:00:00+00:00",
            "cost_by_phase": {"phase-1": "$5.00"},
            "cost_by_model": {},
            "cost_by_tool": {},
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["costs", "execution", "exec-xyz"])
        assert result.exit_code == 0
        assert "$10.00" in result.stdout
        assert "phase-1" in result.stdout
