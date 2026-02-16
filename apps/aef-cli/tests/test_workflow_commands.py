"""Tests for workflow CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from aef_api.types import Ok, WorkflowSummary, WorkflowValidation
from aef_cli.main import app

runner = CliRunner()


@pytest.mark.unit
class TestWorkflowHelp:
    def test_workflow_help(self) -> None:
        result = runner.invoke(app, ["workflow", "--help"])
        assert result.exit_code == 0
        for cmd in ("create", "list", "show", "run", "status", "validate"):
            assert cmd in result.stdout


@pytest.mark.unit
class TestWorkflowList:
    def test_list_empty(self) -> None:
        with patch("aef_api.v1.workflows.list_workflows", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([])
            result = runner.invoke(app, ["workflow", "list"])
        assert result.exit_code == 0
        assert "No workflows found" in result.stdout

    def test_list_with_results(self) -> None:
        summary = WorkflowSummary(
            id="wf-123-abc-def",
            name="Test Workflow",
            workflow_type="research",
            classification="standard",
            phase_count=3,
        )
        with patch("aef_api.v1.workflows.list_workflows", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([summary])
            result = runner.invoke(app, ["workflow", "list"])
        assert result.exit_code == 0
        assert "Test Workflow" in result.stdout
        assert "research" in result.stdout


@pytest.mark.unit
class TestWorkflowCreate:
    def test_create_success(self) -> None:
        with patch("aef_api.v1.workflows.create_workflow", new_callable=AsyncMock) as mock:
            mock.return_value = Ok("wf-new-id")
            result = runner.invoke(
                app,
                ["workflow", "create", "My Workflow", "--type", "research"],
            )
        assert result.exit_code == 0
        assert "My Workflow" in result.stdout

    def test_create_help(self) -> None:
        result = runner.invoke(app, ["workflow", "create", "--help"])
        assert result.exit_code == 0
        assert "--type" in result.stdout
        assert "--repo" in result.stdout


@pytest.mark.unit
class TestWorkflowValidate:
    def test_validate_help(self) -> None:
        result = runner.invoke(app, ["workflow", "validate", "--help"])
        assert result.exit_code == 0

    def test_validate_valid_file(self) -> None:
        validation = WorkflowValidation(
            valid=True,
            name="Test",
            workflow_type="research",
            phase_count=2,
            errors=[],
        )
        with patch("aef_api.v1.workflows.validate_yaml", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(validation)
            result = runner.invoke(app, ["workflow", "validate", "/tmp/test.yaml"])
        assert result.exit_code == 0
        assert "Valid" in result.stdout

    def test_validate_invalid_file(self) -> None:
        validation = WorkflowValidation(
            valid=False,
            name="",
            workflow_type="",
            phase_count=0,
            errors=["Missing required field: name"],
        )
        with patch("aef_api.v1.workflows.validate_yaml", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(validation)
            result = runner.invoke(app, ["workflow", "validate", "/tmp/bad.yaml"])
        assert result.exit_code == 1
        assert "Invalid" in result.stdout


@pytest.mark.unit
class TestWorkflowRun:
    def test_run_not_found(self) -> None:
        with patch("aef_api.v1.workflows.list_workflows", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([])
            result = runner.invoke(app, ["workflow", "run", "nonexistent"])
        assert result.exit_code == 1
        assert "No workflow found" in result.stdout

    def test_run_dry_run(self) -> None:
        summary = WorkflowSummary(
            id="wf-test-123",
            name="Test Workflow",
            workflow_type="research",
            classification="standard",
            phase_count=2,
        )
        with patch("aef_api.v1.workflows.list_workflows", new_callable=AsyncMock) as mock:
            mock.return_value = Ok([summary])
            result = runner.invoke(app, ["workflow", "run", "wf-test-123", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.stdout
