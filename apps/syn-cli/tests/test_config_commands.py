"""Tests for config CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from syn_api.types import ConfigIssue, ConfigSnapshot, Ok
from syn_cli.main import app

runner = CliRunner()


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
        snapshot = ConfigSnapshot(
            app={"environment": "development", "debug": True},
            database={"url": "sqlite:///:memory:"},
            agents={"default_provider": "claude"},
            storage={"type": "memory"},
        )
        with patch("syn_api.v1.config.get_config", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(snapshot)
            result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Application" in result.stdout
        assert "Database" in result.stdout
        assert "Agent Configuration" in result.stdout
        assert "Storage" in result.stdout


@pytest.mark.unit
class TestConfigValidate:
    def test_validate_no_issues(self) -> None:
        with patch("syn_api.v1.config.validate_config", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([])
            result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "No issues found" in result.stdout

    def test_validate_with_warnings(self) -> None:
        issues = [
            ConfigIssue(level="warning", category="agents", message="No API key set"),
        ]
        with patch("syn_api.v1.config.validate_config", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(issues)
            result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "No API key" in result.stdout

    def test_validate_with_errors(self) -> None:
        issues = [
            ConfigIssue(level="error", category="database", message="DB unreachable"),
        ]
        with patch("syn_api.v1.config.validate_config", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(issues)
            result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 1
        assert "DB unreachable" in result.stdout


@pytest.mark.unit
class TestConfigEnv:
    def test_env_template(self) -> None:
        with patch("syn_api.v1.config.get_env_template", new_callable=AsyncMock) as mock:
            mock.return_value = Ok("APP_ENVIRONMENT=development\nDATABASE_URL=sqlite:///:memory:")
            result = runner.invoke(app, ["config", "env"])
        assert result.exit_code == 0
        assert "APP_ENVIRONMENT" in result.stdout
