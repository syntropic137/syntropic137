"""Tests for metrics CLI commands."""

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
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


@pytest.mark.unit
class TestMetrics:
    def test_show_metrics(self) -> None:
        data = {
            "total_workflows": 3,
            "completed_workflows": 2,
            "failed_workflows": 1,
            "total_sessions": 10,
            "total_input_tokens": 50000,
            "total_output_tokens": 30000,
            "total_tokens": 80000,
            "total_cost_usd": "5.00",
            "total_artifacts": 15,
            "phases": [],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.metrics.get_client", return_value=client):
            result = runner.invoke(app, ["metrics", "show"])
        assert result.exit_code == 0
        assert "$5.00" in result.stdout
        assert "80.0K" in result.stdout

    def test_show_metrics_with_phases(self) -> None:
        data = {
            "total_workflows": 1,
            "completed_workflows": 1,
            "failed_workflows": 0,
            "total_sessions": 2,
            "total_tokens": 10000,
            "total_cost_usd": "1.00",
            "total_artifacts": 3,
            "phases": [
                {
                    "phase_name": "research",
                    "status": "completed",
                    "total_tokens": 5000,
                    "cost_usd": "0.50",
                    "duration_seconds": 30.0,
                    "artifact_count": 2,
                },
            ],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.commands.metrics.get_client", return_value=client):
            result = runner.invoke(app, ["metrics", "show"])
        assert result.exit_code == 0
        assert "research" in result.stdout

    def test_metrics_connection_error(self) -> None:
        with patch("syn_cli.commands.metrics.get_client", side_effect=Exception("conn")):
            result = runner.invoke(app, ["metrics", "show"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout
