"""Tests for workflow run and status commands.

These tests validate the CLI commands for workflow execution.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from aef_adapters.storage import (
    get_event_publisher,
    get_workflow_repository,
    reset_storage,
)
from aef_cli.main import app
from aef_domain.contexts.orchestration._shared.WorkflowValueObjects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from aef_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from aef_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_storage() -> None:
    """Reset storage before each test."""
    reset_storage()


@pytest.fixture
def sample_workflow_id() -> str:
    """Create a sample workflow and return its ID."""
    import asyncio

    repository = get_workflow_repository()
    publisher = get_event_publisher()
    handler = CreateWorkflowTemplateHandler(repository=repository, event_publisher=publisher)

    phases = [
        PhaseDefinition(
            phase_id="research",
            name="Research Phase",
            order=1,
            description="Conduct research on the topic",
            input_artifact_types=["topic"],
            output_artifact_types=["research_summary"],
            # Prompt template is required for execution
            prompt_template="Research the given topic and provide a summary.",
        ),
        PhaseDefinition(
            phase_id="planning",
            name="Planning Phase",
            order=2,
            description="Create a plan based on research",
            input_artifact_types=["research_summary"],
            output_artifact_types=["plan"],
            prompt_template="Create a detailed plan based on the research: {{research}}",
        ),
    ]

    command = CreateWorkflowTemplateCommand(
        aggregate_id="test-workflow-run-123",
        name="Test Run Workflow",
        description="A workflow for testing run command",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.STANDARD,
        repository_url="https://github.com/test/repo",
        phases=phases,
    )

    asyncio.run(handler.handle(command))
    return "test-workflow-run-123"


@pytest.mark.unit
class TestWorkflowRunCommand:
    """Tests for the workflow run command."""

    def test_run_workflow_not_found(self) -> None:
        """Test running a non-existent workflow."""
        result = runner.invoke(app, ["workflow", "run", "nonexistent-workflow"])

        assert result.exit_code == 1
        assert "No workflow found" in result.stdout

    def test_run_workflow_dry_run(self, sample_workflow_id: str) -> None:
        """Test dry run shows execution plan without executing."""
        result = runner.invoke(app, ["workflow", "run", sample_workflow_id, "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN MODE" in result.stdout
        assert "Execution Plan" in result.stdout
        assert "Research Phase" in result.stdout
        assert "Planning Phase" in result.stdout
        assert "valid and ready to execute" in result.stdout

    def test_run_workflow_partial_id(self, sample_workflow_id: str) -> None:
        """Test running workflow with partial ID match."""
        # Use partial ID (sample_workflow_id fixture ensures workflow exists)
        _ = sample_workflow_id  # Mark as used
        result = runner.invoke(app, ["workflow", "run", "test-workflow-run", "--dry-run"])

        assert result.exit_code == 0
        assert "Test Run Workflow" in result.stdout

    def test_run_workflow_with_inputs(self, sample_workflow_id: str) -> None:
        """Test running workflow with input variables."""
        result = runner.invoke(
            app,
            [
                "workflow",
                "run",
                sample_workflow_id,
                "--input",
                "topic=AI agents",
                "--input",
                "depth=3",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "Inputs" in result.stdout
        assert "topic" in result.stdout
        assert "AI agents" in result.stdout
        assert "depth" in result.stdout

    @pytest.mark.skip(reason="Requires mock agent setup - see #38")
    def test_run_workflow_executes_successfully(self, sample_workflow_id: str) -> None:
        """Test actual workflow execution."""
        result = runner.invoke(
            app,
            ["workflow", "run", sample_workflow_id, "--input", "topic=Testing"],
        )

        # With mock agent, should complete
        assert result.exit_code == 0
        assert "completed successfully" in result.stdout or "Summary" in result.stdout

    @pytest.mark.skip(reason="Requires mock agent setup - see #38")
    def test_run_workflow_quiet_mode(self, sample_workflow_id: str) -> None:
        """Test quiet mode has minimal output."""
        result = runner.invoke(
            app,
            ["workflow", "run", sample_workflow_id, "--quiet"],
        )

        assert result.exit_code == 0
        # Quiet mode should not have the detailed table
        # but should have summary
        assert "Summary" in result.stdout


class TestWorkflowStatusCommand:
    """Tests for the workflow status command."""

    def test_status_workflow_not_found(self) -> None:
        """Test status for non-existent workflow."""
        result = runner.invoke(app, ["workflow", "status", "nonexistent-workflow"])

        assert result.exit_code == 1
        assert "No workflow found" in result.stdout

    def test_status_no_executions(self, sample_workflow_id: str) -> None:
        """Test status when workflow hasn't been executed."""
        result = runner.invoke(app, ["workflow", "status", sample_workflow_id])

        assert result.exit_code == 0
        assert "Test Run Workflow" in result.stdout
        assert "No execution history" in result.stdout

    def test_status_after_execution(self, sample_workflow_id: str) -> None:
        """Test status after workflow has been executed."""
        # First, run the workflow
        runner.invoke(app, ["workflow", "run", sample_workflow_id, "--input", "topic=Test"])

        # Then check status
        result = runner.invoke(app, ["workflow", "status", sample_workflow_id])

        assert result.exit_code == 0
        assert "Test Run Workflow" in result.stdout


class TestInputParsing:
    """Tests for input parsing functionality."""

    def test_parse_string_input(self, sample_workflow_id: str) -> None:
        """Test parsing string inputs."""
        result = runner.invoke(
            app,
            ["workflow", "run", sample_workflow_id, "--input", "name=hello", "--dry-run"],
        )

        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_parse_quoted_string(self, sample_workflow_id: str) -> None:
        """Test parsing quoted strings with spaces."""
        result = runner.invoke(
            app,
            [
                "workflow",
                "run",
                sample_workflow_id,
                "--input",
                'topic="AI agent systems"',
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "AI agent systems" in result.stdout

    def test_parse_integer(self, sample_workflow_id: str) -> None:
        """Test parsing integer inputs."""
        result = runner.invoke(
            app,
            ["workflow", "run", sample_workflow_id, "--input", "count=42", "--dry-run"],
        )

        assert result.exit_code == 0
        assert "42" in result.stdout

    def test_parse_boolean(self, sample_workflow_id: str) -> None:
        """Test parsing boolean inputs."""
        result = runner.invoke(
            app,
            ["workflow", "run", sample_workflow_id, "--input", "verbose=true", "--dry-run"],
        )

        assert result.exit_code == 0
        assert "verbose" in result.stdout

    def test_parse_invalid_input_warning(self, sample_workflow_id: str) -> None:
        """Test warning for invalid input format."""
        result = runner.invoke(
            app,
            [
                "workflow",
                "run",
                sample_workflow_id,
                "--input",
                "invalid_no_equals",
                "--dry-run",
            ],
        )

        # Should warn but continue
        assert "Warning" in result.stdout or result.exit_code == 0
