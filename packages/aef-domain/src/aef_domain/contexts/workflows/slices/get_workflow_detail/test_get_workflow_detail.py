"""Tests for get_workflow_detail query slice.

Note: WorkflowDetailProjection is for workflow TEMPLATES, not executions.
Templates don't have status - only runs_count.
For execution status, see WorkflowExecutionDetailProjection.
"""

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


@pytest.mark.unit
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
    """Tests for WorkflowDetailProjection (TEMPLATE projection)."""

    @pytest.mark.asyncio
    async def test_handles_workflow_created(self, projection: WorkflowDetailProjection):
        """Test projection handles WorkflowCreated event."""
        event_data = {
            "workflow_id": "wf-1",
            "name": "Test Workflow",
            "workflow_type": "research",
            "classification": "technical",
            "description": "A test workflow",
            "phases": [{"id": "p1", "name": "Phase 1", "agent_type": "claude"}],
            "created_at": datetime.now(UTC),
        }

        await projection.on_workflow_created(event_data)

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert detail.id == "wf-1"
        assert detail.name == "Test Workflow"
        assert detail.workflow_type == "research"
        assert len(detail.phases) == 1
        assert detail.runs_count == 0  # Templates start with 0 runs

    @pytest.mark.asyncio
    async def test_handles_workflow_execution_started_increments_runs(
        self, projection: WorkflowDetailProjection
    ):
        """Test projection increments runs_count on execution start."""
        # First create the workflow template
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "technical",
                "phases": [],
            }
        )

        # Start an execution
        await projection.on_workflow_execution_started(
            {"workflow_id": "wf-1", "execution_id": "exec-1"}
        )

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert detail.runs_count == 1

        # Start another execution
        await projection.on_workflow_execution_started(
            {"workflow_id": "wf-1", "execution_id": "exec-2"}
        )

        detail = await projection.get_by_id("wf-1")
        assert detail.runs_count == 2

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_workflow(self, projection: WorkflowDetailProjection):
        """Test projection returns None for non-existent workflow."""
        detail = await projection.get_by_id("non-existent")
        assert detail is None

    @pytest.mark.asyncio
    async def test_phases_are_phase_definitions(self, projection: WorkflowDetailProjection):
        """Test that phases are definitions, not execution state."""
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "technical",
                "phases": [
                    {"id": "p1", "name": "Research", "agent_type": "claude", "order": 0},
                    {"id": "p2", "name": "Innovate", "agent_type": "claude", "order": 1},
                    {"id": "p3", "name": "Synthesize", "agent_type": "claude", "order": 2},
                ],
            }
        )

        detail = await projection.get_by_id("wf-1")
        assert detail is not None
        assert len(detail.phases) == 3

        # Phases should be definitions with id, name, order, agent_type
        phase_1 = detail.phases[0]
        assert phase_1.id == "p1"
        assert phase_1.name == "Research"
        assert phase_1.order == 0


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
