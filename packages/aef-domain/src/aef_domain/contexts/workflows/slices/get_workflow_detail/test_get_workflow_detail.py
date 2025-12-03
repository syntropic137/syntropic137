"""Tests for get_workflow_detail query slice."""

import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

# Ensure test environment before any imports
os.environ["APP_ENVIRONMENT"] = "test"

from aef_adapters.projection_stores.memory_store import InMemoryProjectionStore
from aef_domain.contexts.workflows.domain.queries.get_workflow_detail import (
    GetWorkflowDetailQuery,
)
from aef_domain.contexts.workflows.slices.get_workflow_detail.handler import (
    GetWorkflowDetailHandler,
)
from aef_domain.contexts.workflows.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)


@pytest.fixture
def memory_store() -> InMemoryProjectionStore:
    """Create a fresh in-memory store for tests."""
    return InMemoryProjectionStore()


@pytest.fixture
def projection(memory_store: InMemoryProjectionStore) -> WorkflowDetailProjection:
    """Create projection with test store."""
    return WorkflowDetailProjection(memory_store)


@pytest.fixture
def handler(projection: WorkflowDetailProjection) -> GetWorkflowDetailHandler:
    """Create handler with test projection."""
    return GetWorkflowDetailHandler(projection)


class TestGetWorkflowDetailQuery:
    """Tests for GetWorkflowDetailQuery DTO."""

    def test_query_creation(self):
        """Test query can be created with workflow_id."""
        query = GetWorkflowDetailQuery(workflow_id="wf-123")
        assert query.workflow_id == "wf-123"
        assert query.include_phases is True  # default
        assert query.include_sessions is False  # default

    def test_query_is_immutable(self):
        """Test query is immutable (frozen dataclass)."""
        query = GetWorkflowDetailQuery(workflow_id="wf-123")
        with pytest.raises(FrozenInstanceError):
            query.workflow_id = "wf-456"  # type: ignore


class TestWorkflowDetailProjection:
    """Tests for WorkflowDetailProjection."""

    @pytest.mark.asyncio
    async def test_handles_workflow_created(self, projection: WorkflowDetailProjection):
        """Test projection handles WorkflowCreated event."""
        event_data = {
            "workflow_id": "wf-1",
            "name": "Test Workflow",
            "workflow_type": "research",
            "classification": "technical",
            "description": "A test workflow",
            "phases": [{"phase_id": "p1", "name": "Phase 1"}],
            "created_at": datetime.now(UTC),
        }

        await projection.on_workflow_created(event_data)

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert detail.id == "wf-1"
        assert detail.name == "Test Workflow"
        assert detail.workflow_type == "research"
        assert detail.status == "pending"
        assert len(detail.phases) == 1

    @pytest.mark.asyncio
    async def test_handles_workflow_completed(self, projection: WorkflowDetailProjection):
        """Test projection handles WorkflowCompleted event."""
        # First create the workflow
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "technical",
                "phases": [],
            }
        )

        # Then complete it
        await projection.on_workflow_completed(
            {"workflow_id": "wf-1", "completed_at": "2024-01-01T12:00:00"}
        )

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert detail.status == "completed"
        assert detail.completed_at is not None

    @pytest.mark.asyncio
    async def test_handles_workflow_failed(self, projection: WorkflowDetailProjection):
        """Test projection handles WorkflowFailed event."""
        # First create the workflow
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "technical",
                "phases": [],
            }
        )

        # Then fail it
        await projection.on_workflow_failed(
            {"workflow_id": "wf-1", "error_message": "Something went wrong"}
        )

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert detail.status == "failed"

    @pytest.mark.asyncio
    async def test_handles_phase_started(self, projection: WorkflowDetailProjection):
        """Test projection updates status on PhaseStarted."""
        # First create the workflow
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "technical",
                "phases": [{"phase_id": "p1", "name": "Phase 1"}],
            }
        )

        # Start a phase
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "started_at": datetime.now(UTC).isoformat()}
        )

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert detail.status == "in_progress"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_workflow(self, projection: WorkflowDetailProjection):
        """Test projection returns None for non-existent workflow."""
        detail = await projection.get_by_id("non-existent")
        assert detail is None


class TestGetWorkflowDetailHandler:
    """Tests for GetWorkflowDetailHandler."""

    @pytest.mark.asyncio
    async def test_handler_returns_workflow_detail(
        self, projection: WorkflowDetailProjection, handler: GetWorkflowDetailHandler
    ):
        """Test handler returns workflow detail."""
        # Setup - create workflow via projection
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "technical",
                "phases": [],
            }
        )

        # Execute query
        query = GetWorkflowDetailQuery(workflow_id="wf-1")
        result = await handler.handle(query)

        # Assert
        assert result is not None
        assert result.id == "wf-1"
        assert result.name == "Test Workflow"

    @pytest.mark.asyncio
    async def test_handler_returns_none_for_missing(self, handler: GetWorkflowDetailHandler):
        """Test handler returns None for missing workflow."""
        query = GetWorkflowDetailQuery(workflow_id="non-existent")
        result = await handler.handle(query)
        assert result is None
