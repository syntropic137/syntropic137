"""Tests for main CLI entry point."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()


@pytest.mark.unit
class TestVersionCommand:
    def test_shows_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Syntropic137" in result.stdout
        assert "0.2.0" in result.stdout

    def test_version_v_prefix(self) -> None:
        result = runner.invoke(app, ["version"])
        assert "v0.2.0" in result.stdout


@pytest.mark.unit
class TestMainHelp:
    def test_help_lists_all_subcommands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in ("workflow", "agent", "config", "control", "triggers", "version", "run"):
            assert name in result.stdout

    def test_run_shortcut_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.stdout
        assert "--input" in result.stdout
