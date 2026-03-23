"""Tests for workflow seeder service."""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from syn_domain.contexts.orchestration.seed_workflow.SeedWorkflowService import (
    _build_create_command,
    _handle_seed_error,
)

from syn_adapters.storage import (
    get_event_publisher,
    get_event_store,
    get_workflow_repository,
    reset_storage,
)
from syn_domain.contexts.orchestration.seed_workflow import WorkflowSeeder
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)

SAMPLE_WORKFLOW_YAML = """
id: seeder-test-workflow
name: Seeder Test Workflow
description: A workflow for testing the seeder

type: research
classification: simple

repository:
  url: https://github.com/test/repo
  ref: main

phases:
  - id: test-phase
    name: Test Phase
    order: 1
    description: A test phase
    output_artifacts:
      - test_output
"""


@pytest.fixture(autouse=True)
def _reset_stores() -> None:
    """Reset in-memory stores before each test."""
    reset_storage()


@pytest.fixture
def handler() -> CreateWorkflowTemplateHandler:
    """Create a handler for testing."""
    repository = get_workflow_repository()
    publisher = get_event_publisher()
    return CreateWorkflowTemplateHandler(repository=repository, event_publisher=publisher)


@pytest.fixture
def seeder(handler: CreateWorkflowTemplateHandler) -> WorkflowSeeder:
    """Create a seeder for testing."""
    return WorkflowSeeder(handler)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_from_file(seeder: WorkflowSeeder) -> None:
    """Test seeding a single workflow from file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(SAMPLE_WORKFLOW_YAML)
        f.flush()
        path = Path(f.name)

    try:
        result = await seeder.seed_from_file(path)

        assert result.success is True
        assert result.workflow_id == "seeder-test-workflow"
        assert result.name == "Seeder Test Workflow"
        assert result.error is None
    finally:
        path.unlink()


@pytest.mark.asyncio
async def test_seed_from_file_dry_run(seeder: WorkflowSeeder) -> None:
    """Test dry-run mode doesn't create workflow."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(SAMPLE_WORKFLOW_YAML)
        f.flush()
        path = Path(f.name)

    try:
        result = await seeder.seed_from_file(path, dry_run=True)

        assert result.success is True

        # Verify no workflow was actually created
        event_store = get_event_store()
        events = event_store.get_all_events()
        assert len(events) == 0
    finally:
        path.unlink()


@pytest.mark.asyncio
async def test_seed_from_directory(seeder: WorkflowSeeder) -> None:
    """Test seeding multiple workflows from directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        # Create two workflow files
        (dir_path / "workflow1.yaml").write_text("""
id: dir-workflow-1
name: Directory Workflow 1
phases:
  - id: p1
    name: Phase 1
    order: 1
""")
        (dir_path / "workflow2.yaml").write_text("""
id: dir-workflow-2
name: Directory Workflow 2
phases:
  - id: p1
    name: Phase 1
    order: 1
""")

        report = await seeder.seed_from_directory(dir_path)

        assert report.total == 2
        assert report.succeeded == 2
        assert report.failed == 0
        assert report.all_succeeded is True


@pytest.mark.asyncio
async def test_skip_existing_workflow(seeder: WorkflowSeeder) -> None:
    """Test that existing workflows are skipped."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(SAMPLE_WORKFLOW_YAML)
        f.flush()
        path = Path(f.name)

    try:
        # Seed once
        result1 = await seeder.seed_from_file(path)
        assert result1.success is True

        # Seed again - should be skipped
        result2 = await seeder.seed_from_file(path)
        assert result2.success is False
        assert "already exists" in (result2.error or "")
    finally:
        path.unlink()


@pytest.mark.asyncio
async def test_register_existing_workflows(seeder: WorkflowSeeder) -> None:
    """Test registering existing workflow IDs for skipping."""
    seeder.register_existing({"existing-workflow-id"})

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
id: existing-workflow-id
name: Already Exists
phases:
  - id: p1
    name: Phase 1
    order: 1
""")
        f.flush()
        path = Path(f.name)

    try:
        result = await seeder.seed_from_file(path)
        assert result.success is False
        assert "already exists" in (result.error or "")
    finally:
        path.unlink()


@pytest.mark.asyncio
async def test_seed_report_statistics(seeder: WorkflowSeeder) -> None:
    """Test that seed report correctly tracks statistics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        # Create 3 valid workflows
        for i in range(3):
            (dir_path / f"workflow{i}.yaml").write_text(f"""
id: stats-workflow-{i}
name: Stats Workflow {i}
phases:
  - id: p1
    name: Phase 1
    order: 1
""")

        report = await seeder.seed_from_directory(dir_path)

        assert report.total == 3
        assert report.succeeded == 3
        assert report.failed == 0
        assert report.skipped == 0
        assert len(report.results) == 3


# =========================================================================
# Extracted helper tests
# =========================================================================


@pytest.mark.unit
class TestBuildCreateCommand:
    """Tests for _build_create_command helper."""

    def test_builds_command_from_definition(self) -> None:
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        definition = WorkflowDefinition(
            id="wf-1", name="Test", type="research", classification="simple",
            repository={"url": "https://github.com/test/repo", "ref": "main"},
            phases=[{"id": "p-1", "name": "Phase 1", "order": 1}],
        )
        cmd = _build_create_command(definition)
        assert cmd.aggregate_id == "wf-1"
        assert cmd.name == "Test"
        assert cmd.repository_url == "https://github.com/test/repo"

    def test_uses_placeholder_url_without_repository(self) -> None:
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        definition = WorkflowDefinition(
            id="wf-2", name="No Repo",
            phases=[{"id": "p-1", "name": "Phase 1", "order": 1}],
        )
        cmd = _build_create_command(definition)
        assert "placeholder" in cmd.repository_url


@pytest.mark.unit
class TestHandleSeedError:
    """Tests for _handle_seed_error helper."""

    def test_duplicate_error_returns_exists(self) -> None:
        existing: set[str] = set()
        result = _handle_seed_error(
            Exception("Precondition failed: stream exists"),
            "wf-1", "Test", existing,
        )
        assert result.success is False
        assert "already exists" in (result.error or "")
        assert "wf-1" in existing

    def test_real_error_returns_failure(self) -> None:
        existing: set[str] = set()
        result = _handle_seed_error(
            RuntimeError("connection refused"), "wf-1", "Test", existing,
        )
        assert result.success is False
        assert "connection refused" in (result.error or "")
        assert "wf-1" not in existing
