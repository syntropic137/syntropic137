"""Integration tests for CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from aef_cli.main import app

runner = CliRunner()


class TestVersionCommand:
    """Tests for version command."""

    def test_version_shows_version(self) -> None:
        """Test version command displays version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Agentic Engineering Framework" in result.stdout
        assert "v" in result.stdout


class TestWorkflowCommands:
    """Tests for workflow CLI commands."""

    def test_workflow_help(self) -> None:
        """Test workflow --help displays usage."""
        result = runner.invoke(app, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "Manage workflows" in result.stdout

    def test_workflow_create_help(self) -> None:
        """Test workflow create --help displays options."""
        result = runner.invoke(app, ["workflow", "create", "--help"])
        assert result.exit_code == 0
        assert "NAME" in result.stdout  # name is an argument
        assert "--type" in result.stdout
        assert "--repo" in result.stdout

    def test_workflow_list_empty(self) -> None:
        """Test workflow list with no workflows."""
        result = runner.invoke(app, ["workflow", "list"])
        # Should succeed even with no workflows
        assert result.exit_code == 0


class TestAgentCommands:
    """Tests for agent CLI commands."""

    def test_agent_help(self) -> None:
        """Test agent --help displays usage."""
        result = runner.invoke(app, ["agent", "--help"])
        assert result.exit_code == 0
        assert "AI agent management" in result.stdout

    def test_agent_list(self) -> None:
        """Test agent list shows providers."""
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "claude" in result.stdout.lower()
        assert "openai" in result.stdout.lower()

    def test_agent_test_help(self) -> None:
        """Test agent test --help displays options."""
        result = runner.invoke(app, ["agent", "test", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.stdout
        assert "--prompt" in result.stdout

    def test_agent_chat_help(self) -> None:
        """Test agent chat --help displays options."""
        result = runner.invoke(app, ["agent", "chat", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.stdout
        assert "--system" in result.stdout


class TestConfigCommands:
    """Tests for config CLI commands."""

    def test_config_help(self) -> None:
        """Test config --help displays usage."""
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "Configuration management" in result.stdout

    def test_config_show(self) -> None:
        """Test config show displays configuration."""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Application" in result.stdout
        assert "Database" in result.stdout
        assert "Agent Configuration" in result.stdout

    def test_config_validate(self) -> None:
        """Test config validate checks configuration."""
        result = runner.invoke(app, ["config", "validate"])
        # Should succeed (may have warnings)
        assert result.exit_code == 0
        assert "Validating configuration" in result.stdout

    def test_config_env(self) -> None:
        """Test config env shows template."""
        result = runner.invoke(app, ["config", "env"])
        assert result.exit_code == 0
        assert "APP_ENVIRONMENT" in result.stdout
        assert "DATABASE_URL" in result.stdout
        assert "ANTHROPIC_API_KEY" in result.stdout


class TestMainCommands:
    """Tests for main app commands."""

    def test_main_help(self) -> None:
        """Test main --help displays all commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "workflow" in result.stdout
        assert "agent" in result.stdout
        assert "config" in result.stdout
        assert "version" in result.stdout

    def test_run_help(self) -> None:
        """Test run --help displays options."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "workflow" in result.stdout.lower()
        assert "--dry-run" in result.stdout

    def test_seed_help(self) -> None:
        """Test seed --help displays options."""
        result = runner.invoke(app, ["seed", "--help"])
        assert result.exit_code == 0
        assert "--path" in result.stdout

    def test_run_dry_run(self) -> None:
        """Test run command with dry-run flag."""
        result = runner.invoke(app, ["run", "test-workflow", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.stdout.lower() or "Dry run" in result.stdout


class TestWorkflowCreateCommand:
    """Tests for workflow create command."""

    def test_workflow_create_basic(self) -> None:
        """Test creating a basic workflow."""
        result = runner.invoke(
            app,
            ["workflow", "create", "Test Workflow", "--type", "research"],
        )
        # Should succeed or show appropriate message
        assert result.exit_code == 0

    def test_workflow_validate_help(self) -> None:
        """Test workflow validate --help."""
        result = runner.invoke(app, ["workflow", "validate", "--help"])
        assert result.exit_code == 0
        assert "path" in result.stdout.lower()

    def test_workflow_seed_help(self) -> None:
        """Test workflow seed --help."""
        result = runner.invoke(app, ["workflow", "seed", "--help"])
        assert result.exit_code == 0
        assert "directory" in result.stdout.lower()

    def test_workflow_show_help(self) -> None:
        """Test workflow show --help."""
        result = runner.invoke(app, ["workflow", "show", "--help"])
        assert result.exit_code == 0
        assert "workflow_id" in result.stdout.lower() or "WORKFLOW_ID" in result.stdout


class TestConfigShowCommand:
    """Tests for config show command with options."""

    def test_config_show_without_secrets(self) -> None:
        """Test config show hides secrets by default."""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        # Should not show actual secret values
        assert "sk-" not in result.stdout  # No API keys exposed


class TestAgentTestCommand:
    """Tests for agent test command."""

    def test_agent_test_unknown_provider(self) -> None:
        """Test agent test with unknown provider."""
        result = runner.invoke(app, ["agent", "test", "--provider", "unknown"])
        assert result.exit_code == 1
        assert "Unknown provider" in result.stdout
