"""Tests for trigger CLI commands."""

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
    client.patch.side_effect = _next_response
    client.delete.side_effect = _next_response
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


@pytest.mark.unit
class TestTriggerHelp:
    def test_triggers_help(self) -> None:
        result = runner.invoke(app, ["triggers", "--help"])
        assert result.exit_code == 0
        for cmd in (
            "register",
            "enable",
            "list",
            "show",
            "history",
            "pause",
            "resume",
            "delete",
            "disable",
        ):
            assert cmd in result.stdout


@pytest.mark.unit
class TestTriggerList:
    def test_list_empty(self) -> None:
        client = _mock_client(_mock_response(200, {"triggers": []}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "list"])
        assert result.exit_code == 0
        assert "No triggers found" in result.stdout

    def test_list_with_results(self) -> None:
        triggers = [
            {
                "trigger_id": "tr-001",
                "name": "Self-Healing CI",
                "event": "check_run.completed",
                "repository": "owner/repo",
                "status": "active",
                "fire_count": 5,
            }
        ]
        client = _mock_client(_mock_response(200, {"triggers": triggers}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "list"])
        assert result.exit_code == 0
        assert "Self-Healing CI" in result.stdout
        assert "active" in result.stdout


@pytest.mark.unit
class TestTriggerRegister:
    def test_register_success(self) -> None:
        client = _mock_client(_mock_response(200, {"trigger_id": "tr-new-001"}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(
                app,
                [
                    "triggers",
                    "register",
                    "--name",
                    "My Trigger",
                    "--event",
                    "check_run.completed",
                    "--repository",
                    "owner/repo",
                    "--workflow",
                    "wf-001",
                ],
            )
        assert result.exit_code == 0
        assert "Trigger registered" in result.stdout
        assert "tr-new-001" in result.stdout

    def test_register_invalid_condition(self) -> None:
        result = runner.invoke(
            app,
            [
                "triggers",
                "register",
                "--name",
                "Bad",
                "--event",
                "push",
                "--repository",
                "o/r",
                "--workflow",
                "wf",
                "--condition",
                "badformat",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid condition" in result.stdout


@pytest.mark.unit
class TestTriggerPauseResume:
    def test_pause_success(self) -> None:
        client = _mock_client(_mock_response(200, {}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "pause", "tr-001"])
        assert result.exit_code == 0
        assert "paused" in result.stdout.lower()

    def test_resume_success(self) -> None:
        client = _mock_client(_mock_response(200, {}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "resume", "tr-001"])
        assert result.exit_code == 0
        assert "resumed" in result.stdout.lower()


@pytest.mark.unit
class TestTriggerDelete:
    def test_delete_success(self) -> None:
        client = _mock_client(_mock_response(200, {}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "delete", "tr-001"])
        assert result.exit_code == 0
        assert "deleted" in result.stdout.lower()


@pytest.mark.unit
class TestTriggerDisable:
    def test_disable_none(self) -> None:
        client = _mock_client(_mock_response(200, {"count": 0}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "disable", "--repository", "o/r"])
        assert result.exit_code == 0
        assert "No active triggers" in result.stdout

    def test_disable_some(self) -> None:
        client = _mock_client(_mock_response(200, {"count": 3}))
        with patch("syn_cli.commands._api_helpers.get_client", return_value=client):
            result = runner.invoke(app, ["triggers", "disable", "--repository", "o/r"])
        assert result.exit_code == 0
        assert "3" in result.stdout
