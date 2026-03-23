"""Tests for config CLI commands."""

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
class TestConfigHelp:
    def test_config_help(self) -> None:
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        for cmd in ("show", "validate", "env"):
            assert cmd in result.stdout


@pytest.mark.unit
class TestConfigShow:
    def test_show_config(self) -> None:
        snapshot = {
            "app": {"environment": "development", "debug": True},
            "database": {"url": "sqlite:///:memory:"},
            "agents": {"default_provider": "claude"},
            "storage": {"type": "memory"},
        }
        client = _mock_client(_mock_response(200, snapshot))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Application" in result.stdout
        assert "Database" in result.stdout
        assert "Agent Configuration" in result.stdout
        assert "Storage" in result.stdout


@pytest.mark.unit
class TestConfigValidate:
    def test_validate_no_issues(self) -> None:
        client = _mock_client(_mock_response(200, {"issues": []}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "No issues found" in result.stdout

    def test_validate_with_warnings(self) -> None:
        issues = [
            {"level": "warning", "category": "agents", "message": "No API key set"},
        ]
        client = _mock_client(_mock_response(200, {"issues": issues}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "No API key" in result.stdout

    def test_validate_with_errors(self) -> None:
        issues = [
            {"level": "error", "category": "database", "message": "DB unreachable"},
        ]
        client = _mock_client(_mock_response(200, {"issues": issues}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 1
        assert "DB unreachable" in result.stdout


@pytest.mark.unit
class TestConfigEnv:
    def test_env_template(self) -> None:
        client = _mock_client(
            _mock_response(
                200, {"template": "APP_ENVIRONMENT=development\nDATABASE_URL=sqlite:///:memory:"}
            )
        )
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["config", "env"])
        assert result.exit_code == 0
        assert "APP_ENVIRONMENT" in result.stdout
