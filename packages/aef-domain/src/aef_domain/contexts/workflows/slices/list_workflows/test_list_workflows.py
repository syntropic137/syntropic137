"""Tests for the list_workflows query slice.

These tests verify the WorkflowListProjection and ListWorkflowsHandler
work correctly together.

Note: WorkflowListProjection is for TEMPLATES, not executions.
Templates don't have status - only runs_count.
"""

import os
from datetime import UTC, datetime

import pytest

# Set test environment
os.environ["APP_ENVIRONMENT"] = "test"

from aef_adapters.projection_stores import InMemoryProjectionStore
from aef_domain.contexts.workflows.domain.queries import ListWorkflowsQuery
from aef_domain.contexts.workflows.slices.list_workflows import (
    ListWorkflowsHandler,
    WorkflowListProjection,
)


@pytest.fixture
def store() -> InMemoryProjectionStore:
    """Create a fresh in-memory store for testing."""
    return InMemoryProjectionStore()


@pytest.fixture
def projection(store: InMemoryProjectionStore) -> WorkflowListProjection:
    """Create a projection with the test store."""
    return WorkflowListProjection(store)


@pytest.fixture
def handler(projection: WorkflowListProjection) -> ListWorkflowsHandler:
    """Create a handler with the test projection."""
    return ListWorkflowsHandler(projection)


class TestWorkflowListProjection:
    """Tests for WorkflowListProjection (template projection)."""

    @pytest.mark.asyncio
    async def test_on_workflow_created(self, projection: WorkflowListProjection):
        """Test handling WorkflowCreated event."""
        event_data = {
            "workflow_id": "wf-1",
            "name": "Test Workflow",
            "workflow_type": "sequential",
            "classification": "standard",
            "description": "A test workflow",
            "phases": [{"id": "p1"}, {"id": "p2"}],
            "created_at": datetime.now(UTC),
        }

        await projection.on_workflow_created(event_data)

        summaries = await projection.get_all()
        assert len(summaries) == 1
        assert summaries[0].id == "wf-1"
        assert summaries[0].name == "Test Workflow"
        assert summaries[0].phase_count == 2
        assert summaries[0].runs_count == 0  # Templates start with 0 runs

    @pytest.mark.asyncio
    async def test_on_workflow_execution_started_increments_runs(
        self, projection: WorkflowListProjection
    ):
        """Test that WorkflowExecutionStarted increments runs_count."""
        # Create workflow template first
        await projection.on_workflow_created({"workflow_id": "wf-1", "name": "Test", "phases": []})

        # Start an execution
        await projection.on_workflow_execution_started(
            {"workflow_id": "wf-1", "execution_id": "exec-1"}
        )

        summaries = await projection.get_all()
        assert summaries[0].runs_count == 1

        # Start another execution
        await projection.on_workflow_execution_started(
            {"workflow_id": "wf-1", "execution_id": "exec-2"}
        )

        summaries = await projection.get_all()
        assert summaries[0].runs_count == 2

    @pytest.mark.asyncio
    async def test_query_with_workflow_type_filter(self, projection: WorkflowListProjection):
        """Test querying with workflow type filter."""
        await projection.on_workflow_created(
            {"workflow_id": "wf-1", "name": "Research", "workflow_type": "research", "phases": []}
        )
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-2",
                "name": "Implementation",
                "workflow_type": "implementation",
                "phases": [],
            }
        )

        research_workflows = await projection.query(workflow_type_filter="research")
        assert len(research_workflows) == 1
        assert research_workflows[0].id == "wf-1"

        impl_workflows = await projection.query(workflow_type_filter="implementation")
        assert len(impl_workflows) == 1
        assert impl_workflows[0].id == "wf-2"

    @pytest.mark.asyncio
    async def test_query_with_pagination(self, projection: WorkflowListProjection):
        """Test querying with limit and offset."""
        for i in range(5):
            await projection.on_workflow_created(
                {"workflow_id": f"wf-{i}", "name": f"Workflow {i}", "phases": []}
            )

        page1 = await projection.query(limit=2, offset=0)
        assert len(page1) == 2

        page2 = await projection.query(limit=2, offset=2)
        assert len(page2) == 2

        page3 = await projection.query(limit=2, offset=4)
        assert len(page3) == 1


class TestListWorkflowsHandler:
    """Tests for ListWorkflowsHandler."""

    @pytest.mark.asyncio
    async def test_handle_basic_query(
        self, handler: ListWorkflowsHandler, projection: WorkflowListProjection
    ):
        """Test handling a basic query."""
        await projection.on_workflow_created(
            {"workflow_id": "wf-1", "name": "Test Workflow", "phases": []}
        )

        query = ListWorkflowsQuery()
        results = await handler.handle(query)

        assert len(results) == 1
        assert results[0].name == "Test Workflow"

    @pytest.mark.asyncio
    async def test_handle_query_with_filters(
        self, handler: ListWorkflowsHandler, projection: WorkflowListProjection
    ):
        """Test handling a query with filters."""
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-1",
                "name": "Seq Workflow",
                "workflow_type": "sequential",
                "phases": [],
            }
        )
        await projection.on_workflow_created(
            {
                "workflow_id": "wf-2",
                "name": "Par Workflow",
                "workflow_type": "parallel",
                "phases": [],
            }
        )

        query = ListWorkflowsQuery(workflow_type_filter="sequential")
        results = await handler.handle(query)

        assert len(results) == 1
        assert results[0].workflow_type == "sequential"

    @pytest.mark.asyncio
    async def test_handle_empty_results(self, handler: ListWorkflowsHandler):
        """Test handling a query with no results."""
        query = ListWorkflowsQuery()
        results = await handler.handle(query)

        assert results == []
