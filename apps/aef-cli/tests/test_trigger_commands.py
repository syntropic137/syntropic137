"""Tests for trigger CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from aef_api.types import Ok, TriggerSummary
from aef_cli.main import app

runner = CliRunner()


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
        with patch("aef_api.v1.triggers.list_triggers", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([])
            result = runner.invoke(app, ["triggers", "list"])
        assert result.exit_code == 0
        assert "No triggers found" in result.stdout

    def test_list_with_results(self) -> None:
        trigger = TriggerSummary(
            trigger_id="tr-001",
            name="Self-Healing CI",
            event="check_run.completed",
            repository="owner/repo",
            workflow_id="wf-001",
            status="active",
            fire_count=5,
            created_at=None,
        )
        with patch("aef_api.v1.triggers.list_triggers", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([trigger])
            result = runner.invoke(app, ["triggers", "list"])
        assert result.exit_code == 0
        assert "Self-Healing CI" in result.stdout
        assert "active" in result.stdout


@pytest.mark.unit
class TestTriggerRegister:
    def test_register_success(self) -> None:
        with patch("aef_api.v1.triggers.register_trigger", new_callable=AsyncMock) as mock:
            mock.return_value = Ok("tr-new-001")
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
        with patch("aef_api.v1.triggers.pause_trigger", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(None)
            result = runner.invoke(app, ["triggers", "pause", "tr-001"])
        assert result.exit_code == 0
        assert "paused" in result.stdout.lower()

    def test_resume_success(self) -> None:
        with patch("aef_api.v1.triggers.resume_trigger", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(None)
            result = runner.invoke(app, ["triggers", "resume", "tr-001"])
        assert result.exit_code == 0
        assert "resumed" in result.stdout.lower()


@pytest.mark.unit
class TestTriggerDelete:
    def test_delete_success(self) -> None:
        with patch("aef_api.v1.triggers.delete_trigger", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(None)
            result = runner.invoke(app, ["triggers", "delete", "tr-001"])
        assert result.exit_code == 0
        assert "deleted" in result.stdout.lower()


@pytest.mark.unit
class TestTriggerDisable:
    def test_disable_none(self) -> None:
        with patch("aef_api.v1.triggers.disable_triggers", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(0)
            result = runner.invoke(app, ["triggers", "disable", "--repository", "o/r"])
        assert result.exit_code == 0
        assert "No active triggers" in result.stdout

    def test_disable_some(self) -> None:
        with patch("aef_api.v1.triggers.disable_triggers", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(3)
            result = runner.invoke(app, ["triggers", "disable", "--repository", "o/r"])
        assert result.exit_code == 0
        assert "3" in result.stdout
