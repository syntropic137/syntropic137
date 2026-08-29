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

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.queries import ListWorkflowsQuery
from syn_domain.contexts.orchestration.slices.list_workflows import (
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


@pytest.mark.unit
class TestWorkflowListProjection:
    """Tests for WorkflowListProjection (template projection)."""

    @pytest.mark.asyncio
    async def test_on_workflow_template_created(self, projection: WorkflowListProjection):
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

        await projection.on_workflow_template_created(event_data)

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
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-1", "name": "Test", "phases": []}
        )

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
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-1", "name": "Research", "workflow_type": "research", "phases": []}
        )
        await projection.on_workflow_template_created(
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
    async def test_on_workflow_template_archived(self, projection: WorkflowListProjection):
        """Test handling WorkflowTemplateArchived event."""
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-1", "name": "Test", "phases": []}
        )

        await projection.on_workflow_template_archived({"workflow_id": "wf-1"})

        summaries = await projection.get_all(include_archived=True)
        assert len(summaries) == 1
        assert summaries[0].is_archived is True

    @pytest.mark.asyncio
    async def test_query_excludes_archived_by_default(self, projection: WorkflowListProjection):
        """Archived workflows should be excluded from query by default."""
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-1", "name": "Active", "phases": []}
        )
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-2", "name": "Archived", "phases": []}
        )
        await projection.on_workflow_template_archived({"workflow_id": "wf-2"})

        results = await projection.query()
        assert len(results) == 1
        assert results[0].id == "wf-1"

    @pytest.mark.asyncio
    async def test_query_includes_archived_when_requested(self, projection: WorkflowListProjection):
        """include_archived=True should return archived workflows."""
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-1", "name": "Active", "phases": []}
        )
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-2", "name": "Archived", "phases": []}
        )
        await projection.on_workflow_template_archived({"workflow_id": "wf-2"})

        results = await projection.query(include_archived=True)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_all_excludes_archived_by_default(self, projection: WorkflowListProjection):
        """get_all should exclude archived workflows by default."""
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-1", "name": "Active", "phases": []}
        )
        await projection.on_workflow_template_created(
            {"workflow_id": "wf-2", "name": "Archived", "phases": []}
        )
        await projection.on_workflow_template_archived({"workflow_id": "wf-2"})

        results = await projection.get_all()
        assert len(results) == 1
        assert results[0].id == "wf-1"

    @pytest.mark.asyncio
    async def test_query_with_pagination(self, projection: WorkflowListProjection):
        """Test querying with limit and offset."""
        for i in range(5):
            await projection.on_workflow_template_created(
                {"workflow_id": f"wf-{i}", "name": f"Workflow {i}", "phases": []}
            )

        page1 = await projection.query(limit=2, offset=0)
        assert len(page1) == 2

        page2 = await projection.query(limit=2, offset=2)
        assert len(page2) == 2

        page3 = await projection.query(limit=2, offset=4)
        assert len(page3) == 1


@pytest.mark.unit
class TestWorkflowListCount:
    """`count` must describe the whole filtered collection, not one page.

    Reproduces what the live API reported: 32 registered workflows, but
    `GET /api/v1/workflows` answered `total: 20` because the total was computed
    as the length of the returned page. A client that pages until it has
    `total` items therefore stopped after page 1 and never saw the other 12.
    """

    @pytest.mark.asyncio
    async def test_count_ignores_pagination(self, projection: WorkflowListProjection):
        for i in range(32):
            await projection.on_workflow_template_created(
                {"workflow_id": f"wf-{i}", "name": f"Workflow {i}", "phases": []}
            )

        page = await projection.query(limit=20, offset=0)
        assert len(page) == 20, "precondition: the page is capped"
        assert await projection.count() == 32

    @pytest.mark.asyncio
    async def test_count_applies_the_same_filters_as_query(
        self, projection: WorkflowListProjection
    ):
        """A total counted under different filters than its page is worse than none."""
        for i in range(3):
            await projection.on_workflow_template_created(
                {
                    "workflow_id": f"rev-{i}",
                    "name": f"R{i}",
                    "workflow_type": "review",
                    "phases": [],
                }
            )
        for i in range(2):
            await projection.on_workflow_template_created(
                {
                    "workflow_id": f"imp-{i}",
                    "name": f"I{i}",
                    "workflow_type": "implementation",
                    "phases": [],
                }
            )

        assert await projection.count() == 5
        assert await projection.count(workflow_type_filter="review") == 3
        assert await projection.count(workflow_type_filter="implementation") == 2

    @pytest.mark.asyncio
    async def test_count_excludes_archived_by_default(self, projection: WorkflowListProjection):
        for i in range(3):
            await projection.on_workflow_template_created(
                {"workflow_id": f"wf-{i}", "name": f"W{i}", "phases": []}
            )
        await projection.on_workflow_template_archived({"workflow_id": "wf-1"})

        assert await projection.count() == 2
        assert await projection.count(include_archived=True) == 3


class TestListWorkflowsHandler:
    """Tests for ListWorkflowsHandler."""

    @pytest.mark.asyncio
    async def test_handle_basic_query(
        self, handler: ListWorkflowsHandler, projection: WorkflowListProjection
    ):
        """Test handling a basic query."""
        await projection.on_workflow_template_created(
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
        await projection.on_workflow_template_created(
            {
                "workflow_id": "wf-1",
                "name": "Seq Workflow",
                "workflow_type": "sequential",
                "phases": [],
            }
        )
        await projection.on_workflow_template_created(
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


@pytest.mark.unit
class TestWorkflowTemplateUpdatedProjection:
    """Reinstall must refresh the read model (issue #822).

    Without a handler for WorkflowTemplateUpdated the aggregate upserts
    correctly while the list keeps serving the first install's definition, so
    a successful reinstall looks like a no-op to the CLI and dashboard.
    """

    @pytest.mark.asyncio
    async def test_updated_refreshes_the_summary(self, projection: WorkflowListProjection):
        await projection.on_workflow_template_created(
            {
                "workflow_id": "code-review",
                "name": "Code Review",
                "workflow_type": "review",
                "classification": "standard",
                "phases": [{"phase_id": "p1"}],
            }
        )

        await projection.on_workflow_template_updated(
            {
                "workflow_id": "code-review",
                "name": "Code Review v2",
                "workflow_type": "review",
                "classification": "standard",
                "phases": [{"phase_id": "p1"}, {"phase_id": "p2"}],
            }
        )

        summary = await projection._store.get(projection.PROJECTION_NAME, "code-review")
        assert summary is not None
        assert summary["name"] == "Code Review v2"
        assert summary["phase_count"] == 2

    @pytest.mark.asyncio
    async def test_updated_preserves_run_history(self, projection: WorkflowListProjection):
        """Runs belong to the template, not to a particular definition."""
        await projection.on_workflow_template_created(
            {
                "workflow_id": "code-review",
                "name": "Code Review",
                "workflow_type": "review",
                "classification": "standard",
                "phases": [],
            }
        )
        await projection.on_workflow_execution_started({"workflow_id": "code-review"})
        await projection.on_workflow_execution_started({"workflow_id": "code-review"})

        await projection.on_workflow_template_updated(
            {
                "workflow_id": "code-review",
                "name": "Code Review v2",
                "workflow_type": "review",
                "classification": "standard",
                "phases": [],
            }
        )

        summary = await projection._store.get(projection.PROJECTION_NAME, "code-review")
        assert summary is not None
        assert summary["runs_count"] == 2

    @pytest.mark.asyncio
    async def test_updated_unarchives(self, projection: WorkflowListProjection):
        """Reinstalling brings back a template a failed update had archived."""
        await projection.on_workflow_template_created(
            {
                "workflow_id": "code-review",
                "name": "Code Review",
                "workflow_type": "review",
                "classification": "standard",
                "phases": [],
            }
        )
        await projection.on_workflow_template_archived({"workflow_id": "code-review"})

        archived = await projection._store.get(projection.PROJECTION_NAME, "code-review")
        assert archived is not None
        assert archived["is_archived"] is True

        await projection.on_workflow_template_updated(
            {
                "workflow_id": "code-review",
                "name": "Code Review",
                "workflow_type": "review",
                "classification": "standard",
                "phases": [],
            }
        )

        restored = await projection._store.get(projection.PROJECTION_NAME, "code-review")
        assert restored is not None
        assert restored["is_archived"] is False
