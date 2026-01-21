"""Tests for CLI main module."""

import pytest
from typer.testing import CliRunner

from aef_adapters.storage import (
    get_event_publisher,
    get_workflow_repository,
    reset_storage,
)
from aef_cli.main import app
from aef_domain.contexts.workflows._shared.WorkflowValueObjects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from aef_domain.contexts.workflows.slices.create_workflow.CreateWorkflowCommand import (
    CreateWorkflowCommand,
)
from aef_domain.contexts.workflows.slices.create_workflow.CreateWorkflowHandler import (
    CreateWorkflowHandler,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_storage() -> None:
    """Reset storage before each test."""
    reset_storage()


def create_test_workflow(workflow_id: str = "test-workflow") -> str:
    """Helper to create a test workflow."""
    import asyncio

    repository = get_workflow_repository()
    publisher = get_event_publisher()
    handler = CreateWorkflowHandler(repository=repository, event_publisher=publisher)

    command = CreateWorkflowCommand(
        aggregate_id=workflow_id,
        name="Test Workflow",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.STANDARD,
        repository_url="https://github.com/test/repo",
        phases=[
            PhaseDefinition(
                phase_id="phase-1",
                name="Test Phase",
                order=1,
                # Prompt template is required for execution
                prompt_template="Test prompt for {{topic}}",
            )
        ],
    )

    asyncio.run(handler.handle(command))
    return workflow_id


@pytest.mark.unit
class TestCLI:
    """Test CLI commands."""

    def test_version_command(self) -> None:
        """Test version command shows version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Agentic Engineering Framework" in result.stdout
        assert "0.1.0" in result.stdout

    def test_run_command_dry_run(self) -> None:
        """Test run command in dry run mode."""
        workflow_id = create_test_workflow()
        result = runner.invoke(app, ["run", workflow_id, "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN MODE" in result.stdout

    @pytest.mark.skip(reason="Requires mock agent setup - see #38")
    def test_run_command(self) -> None:
        """Test run command."""
        workflow_id = create_test_workflow()
        result = runner.invoke(app, ["run", workflow_id])
        # Should complete (with mock agent)
        assert result.exit_code == 0

    def test_run_command_not_found(self) -> None:
        """Test run command with non-existent workflow."""
        result = runner.invoke(app, ["run", "nonexistent"])
        assert result.exit_code == 1
        assert "No workflow found" in result.stdout

    def test_run_command_with_inputs(self) -> None:
        """Test run command with inputs."""
        workflow_id = create_test_workflow()
        result = runner.invoke(app, ["run", workflow_id, "--input", "topic=test", "--dry-run"])
        assert result.exit_code == 0
        assert "topic" in result.stdout
