"""Tests for main CLI entry point."""

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
class TestHealthCommand:
    def test_healthy(self) -> None:
        data = {"status": "healthy", "mode": "full"}
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.main.get_client", return_value=client):
            result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Healthy" in result.stdout

    def test_degraded(self) -> None:
        data = {
            "status": "healthy",
            "mode": "degraded",
            "degraded_reasons": ["Event store subscription behind"],
        }
        client = _mock_client(_mock_response(200, data))
        with patch("syn_cli.main.get_client", return_value=client):
            result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Degraded" in result.stdout
        assert "subscription behind" in result.stdout

    def test_connection_error(self) -> None:
        with patch("syn_cli.main.get_client", side_effect=Exception("conn refused")):
            result = runner.invoke(app, ["health"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout


@pytest.mark.unit
class TestVersionCommand:
    def test_shows_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Syntropic137" in result.stdout
        assert "0.5.1" in result.stdout

    def test_version_v_prefix(self) -> None:
        result = runner.invoke(app, ["version"])
        assert "v0.5.1" in result.stdout


@pytest.mark.unit
class TestMainHelp:
    def test_help_lists_all_subcommands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in (
            "workflow",
            "agent",
            "config",
            "control",
            "triggers",
            "costs",
            "sessions",
            "metrics",
            "observe",
            "version",
            "run",
            "health",
        ):
            assert name in result.stdout

    def test_run_shortcut_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.stdout
        assert "--input" in result.stdout
