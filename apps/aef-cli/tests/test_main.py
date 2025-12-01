"""Tests for CLI main module."""

from typer.testing import CliRunner

from aef_cli.main import app

runner = CliRunner()


class TestCLI:
    """Test CLI commands."""

    def test_version_command(self):
        """Test version command shows version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Agentic Engineering Framework" in result.stdout
        assert "0.1.0" in result.stdout

    def test_run_command_dry_run(self):
        """Test run command in dry run mode."""
        result = runner.invoke(app, ["run", "test-workflow", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run mode" in result.stdout

    def test_run_command(self):
        """Test run command."""
        result = runner.invoke(app, ["run", "test-workflow"])
        assert result.exit_code == 0
        assert "Starting workflow" in result.stdout

    def test_seed_command(self):
        """Test seed command."""
        result = runner.invoke(app, ["seed"])
        assert result.exit_code == 0
        assert "Workflows seeded" in result.stdout

    def test_seed_command_with_path(self):
        """Test seed command with custom path."""
        result = runner.invoke(app, ["seed", "--path", "/custom/path"])
        assert result.exit_code == 0
        assert "/custom/path" in result.stdout
