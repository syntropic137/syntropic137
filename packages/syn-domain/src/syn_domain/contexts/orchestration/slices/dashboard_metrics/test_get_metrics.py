"""Tests for get_metrics query slice.

The projection counts workflow templates and artifacts only. Execution status
counts, sessions, tokens and cost are read by GET /metrics from their own read
models (#1843, #932), so the projection no longer keeps copies (#2272).
"""

import dataclasses
import os

import pytest

# Ensure test environment before any imports
os.environ["APP_ENVIRONMENT"] = "test"

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType, ContentType
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
    ArtifactCreatedEvent,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
    WorkflowTemplateArchivedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateUpdatedEvent import (
    WorkflowTemplateUpdatedEvent,
)
from syn_domain.contexts.orchestration.domain.queries.get_dashboard_metrics import (
    GetDashboardMetricsQuery,
)
from syn_domain.contexts.orchestration.domain.read_models.dashboard_metrics import (
    DashboardMetrics,
)
from syn_domain.contexts.orchestration.slices.dashboard_metrics.GetDashboardMetricsHandler import (
    GetDashboardMetricsHandler,
)
from syn_domain.contexts.orchestration.slices.dashboard_metrics.projection import (
    DashboardMetricsProjection,
)

pytestmark = pytest.mark.unit


def _archived(workflow_id: str) -> dict:
    """A WorkflowTemplateArchived payload as the dispatch paths deliver it."""
    return WorkflowTemplateArchivedEvent(workflow_id=workflow_id).model_dump()


def _reinstalled(workflow_id: str) -> dict:
    """A WorkflowTemplateUpdated payload: what a reinstall emits (#822)."""
    return WorkflowTemplateUpdatedEvent(
        workflow_id=workflow_id,
        name=workflow_id,
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="",
        repository_ref="main",
        phases=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
    ).model_dump()


@pytest.fixture
def memory_store() -> InMemoryProjectionStore:
    """Create a fresh in-memory store for tests."""
    return InMemoryProjectionStore()


@pytest.fixture
def projection(memory_store: InMemoryProjectionStore) -> DashboardMetricsProjection:
    """Create projection with test store."""
    return DashboardMetricsProjection(memory_store)


@pytest.fixture
def handler(projection: DashboardMetricsProjection) -> GetDashboardMetricsHandler:
    """Create handler with test projection."""
    return GetDashboardMetricsHandler(projection)


@pytest.mark.unit
class TestDashboardMetricsProjection:
    """Tests for DashboardMetricsProjection."""

    @pytest.mark.asyncio
    async def test_initial_metrics_are_zero(self, projection: DashboardMetricsProjection):
        """Test that initial metrics are all zero."""
        metrics = await projection.get_metrics()
        assert metrics.total_workflows == 0
        assert metrics.total_artifacts == 0
        assert metrics.total_artifact_bytes == 0

    @pytest.mark.asyncio
    async def test_workflow_created_increments_total(self, projection: DashboardMetricsProjection):
        """Test WorkflowCreated increments total_workflows."""
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_workflow_template_created({"workflow_id": "wf-2"})

        metrics = await projection.get_metrics()
        assert metrics.total_workflows == 2

    @pytest.mark.asyncio
    async def test_artifact_created_increments_count(self, projection: DashboardMetricsProjection):
        """Test ArtifactCreated increments artifact count."""
        await projection.on_artifact_created({"artifact_id": "a-1"})
        await projection.on_artifact_created({"artifact_id": "a-2"})

        metrics = await projection.get_metrics()
        assert metrics.total_artifacts == 2


class TestGetDashboardMetricsHandler:
    """Tests for GetDashboardMetricsHandler."""

    @pytest.mark.asyncio
    async def test_handler_returns_metrics(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        """Test handler returns metrics correctly."""
        # Setup some data
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_artifact_created({"artifact_id": "a-1"})

        # Execute query
        query = GetDashboardMetricsQuery()
        result = await handler.handle(query)

        # Assert
        assert result.total_workflows == 1
        assert result.total_artifacts == 1


# Kept by GET /metrics from their own read models since #1843 and #932.
_REMOVED_COUNTERS = {
    "active_workflows",
    "completed_workflows",
    "failed_workflows",
    "total_sessions",
    "total_tokens",
    "total_input_tokens",
    "total_output_tokens",
    "total_cache_creation_tokens",
    "total_cache_read_tokens",
}


@pytest.mark.unit
class TestNoCountersGetMetricsDoesNotRead:
    """The projection keeps only what GET /metrics reads from it (#2272)."""

    def test_read_model_carries_only_the_counts_metrics_reads(self):
        fields = {f.name for f in dataclasses.fields(DashboardMetrics)}
        assert fields == {"total_workflows", "total_artifacts", "total_artifact_bytes"}
        assert set(DashboardMetrics().to_dict()) == fields

    def test_projection_no_longer_subscribes_to_execution_or_session_events(
        self, projection: DashboardMetricsProjection
    ):
        # Each of these took a read-modify-write of the single global row.
        subscribed = projection.get_subscribed_event_types() or set()
        assert subscribed.isdisjoint(
            {
                "WorkflowExecutionStarted",
                "PhaseStarted",
                "WorkflowCompleted",
                "WorkflowFailed",
                "SessionStarted",
                "SessionCompleted",
            }
        )
        assert subscribed == {
            "WorkflowTemplateCreated",
            "WorkflowCreated",
            "WorkflowTemplateArchived",
            "WorkflowTemplateUpdated",
            "ArtifactCreated",
        }

    @pytest.mark.asyncio
    async def test_a_row_stored_before_the_bump_reads_without_the_old_counters(
        self, memory_store: InMemoryProjectionStore, projection: DashboardMetricsProjection
    ):
        """A VERSION 5 row still carries the old keys until the rebuild clears it."""
        stale = {"total_workflows": 3, "total_artifacts": 4, "total_artifact_bytes": 0}
        stale.update(dict.fromkeys(_REMOVED_COUNTERS, 7))
        await memory_store.save(
            DashboardMetricsProjection.PROJECTION_NAME,
            DashboardMetricsProjection.METRICS_KEY,
            stale,
        )

        metrics = await projection.get_metrics()
        assert metrics == DashboardMetrics(total_workflows=3, total_artifacts=4)


@pytest.mark.unit
class TestTotalWorkflowsExcludesArchived:
    """total_workflows matches GET /workflows, which hides archived templates (#641)."""

    @pytest.mark.asyncio
    async def test_archived_template_is_not_counted(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        for workflow_id in ("wf-1", "wf-2", "wf-3"):
            await projection.on_workflow_template_created({"workflow_id": workflow_id})
        await projection.on_workflow_template_archived(_archived("wf-2"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 2

    @pytest.mark.asyncio
    async def test_archive_never_drives_count_below_zero(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        await projection.on_workflow_template_archived(_archived("wf-1"))
        await projection.on_workflow_template_archived(_archived("wf-2"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 0

    @pytest.mark.asyncio
    async def test_repeated_archive_counts_once(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        for workflow_id in ("wf-1", "wf-2", "wf-3"):
            await projection.on_workflow_template_created({"workflow_id": workflow_id})
        await projection.on_workflow_template_archived(_archived("wf-1"))
        await projection.on_workflow_template_archived(_archived("wf-1"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 2

    @pytest.mark.asyncio
    async def test_reinstalling_an_archived_template_counts_it_again(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        """A reinstall emits WorkflowTemplateUpdated and un-archives the template (#822)."""
        for workflow_id in ("wf-1", "wf-2", "wf-3"):
            await projection.on_workflow_template_created({"workflow_id": workflow_id})
        await projection.on_workflow_template_archived(_archived("wf-2"))
        await projection.on_workflow_template_updated(_reinstalled("wf-2"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 3

        # Archiving it again after the reinstall is counted again.
        await projection.on_workflow_template_archived(_archived("wf-2"))
        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 2

    @pytest.mark.asyncio
    async def test_updating_a_live_template_does_not_count_it_twice(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        for workflow_id in ("wf-1", "wf-2", "wf-3"):
            await projection.on_workflow_template_created({"workflow_id": workflow_id})
        await projection.on_workflow_template_archived(_archived("wf-3"))
        await projection.on_workflow_template_updated(_reinstalled("wf-1"))
        await projection.on_workflow_template_updated(_reinstalled("wf-1"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 2

    @pytest.mark.asyncio
    async def test_archiving_a_template_never_counted_changes_nothing(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        """A legacy template the list never showed: archiving it must not subtract another."""
        await projection.on_workflow_template_created({"workflow_id": "wf-new"})
        await projection.on_workflow_template_archived(_archived("wf-legacy"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("step", ["archive", "reinstall"])
    async def test_a_failed_save_retried_still_counts_right(
        self,
        memory_store: InMemoryProjectionStore,
        handler: GetDashboardMetricsHandler,
        projection: DashboardMetricsProjection,
        step: str,
    ):
        """A save that fails, then the same event retried, must land the change once."""
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        if step == "reinstall":
            await projection.on_workflow_template_archived(_archived("wf-1"))
        expected = 0 if step == "archive" else 1

        async def apply() -> None:
            if step == "archive":
                await projection.on_workflow_template_archived(_archived("wf-1"))
            else:
                await projection.on_workflow_template_updated(_reinstalled("wf-1"))

        save = memory_store.save
        failed = False

        async def save_failing_once(projection_name: str, key: str, data: dict) -> None:
            # Fail the first write of the metrics record itself: any other
            # record the handler wrote before it has already landed.
            nonlocal failed
            if key == DashboardMetricsProjection.METRICS_KEY and not failed:
                failed = True
                raise RuntimeError("store unavailable")
            await save(projection_name, key, data)

        memory_store.save = save_failing_once  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError):
                await apply()
            await apply()  # the coordinator retries the unacknowledged event
        finally:
            memory_store.save = save  # type: ignore[method-assign]

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == expected

    @pytest.mark.asyncio
    async def test_rebuild_clears_archived_markers(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        """A VERSION-bump rebuild replays from scratch; no archive survives it."""
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_workflow_template_archived(_archived("wf-1"))
        await projection.clear_all_data()

        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_workflow_template_updated(_reinstalled("wf-1"))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_workflows == 1


def _artifact(artifact_id: str, size_bytes: int) -> dict:
    """An ArtifactCreated payload as the dispatch paths deliver it."""
    return ArtifactCreatedEvent(
        artifact_id=artifact_id,
        workflow_id="wf-1",
        phase_id="p1",
        artifact_type=ArtifactType.RESEARCH_SUMMARY,
        content_type=ContentType.TEXT_PLAIN,
        content="x",
        content_hash="h",
        size_bytes=size_bytes,
    ).model_dump()


class TestTotalArtifactBytes:
    """#2274: total_artifact_bytes sums ArtifactCreated.size_bytes."""

    @pytest.mark.asyncio
    async def test_sizes_sum(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        await projection.on_artifact_created(_artifact("a-1", 1200))
        await projection.on_artifact_created(_artifact("a-2", 34))

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_artifacts == 2
        assert result.total_artifact_bytes == 1234

    @pytest.mark.asyncio
    async def test_payload_without_size_counts_the_artifact_and_adds_zero(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        """An older stored payload with no size_bytes key never raises."""
        await projection.on_artifact_created(_artifact("a-1", 500))
        await projection.on_artifact_created({"artifact_id": "a-old"})

        result = await handler.handle(GetDashboardMetricsQuery())
        assert result.total_artifacts == 2
        assert result.total_artifact_bytes == 500
