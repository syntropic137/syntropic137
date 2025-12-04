"""API tests for the AEF Dashboard.

Tests use httpx.AsyncClient for proper async/await support with FastAPI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from aef_adapters.storage import (
    get_artifact_repository,
    get_session_repository,
    get_workflow_repository,
    reset_storage,
)
from aef_dashboard.api.events import clear_events, push_event
from aef_dashboard.main import app
from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate
from aef_domain.contexts.artifacts._shared.value_objects import ArtifactType
from aef_domain.contexts.artifacts.create_artifact.CreateArtifactCommand import (
    CreateArtifactCommand,
)
from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from aef_domain.contexts.sessions._shared.value_objects import OperationType, SessionStatus
from aef_domain.contexts.sessions.complete_session.CompleteSessionCommand import (
    CompleteSessionCommand,
)
from aef_domain.contexts.sessions.record_operation.RecordOperationCommand import (
    RecordOperationCommand,
)
from aef_domain.contexts.sessions.start_session.StartSessionCommand import (
    StartSessionCommand,
)
from aef_domain.contexts.workflows._shared.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from aef_domain.contexts.workflows._shared.WorkflowAggregate import WorkflowAggregate
from aef_domain.contexts.workflows.create_workflow.CreateWorkflowCommand import (
    CreateWorkflowCommand,
)


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async test client using httpx.AsyncClient with ASGITransport."""
    from httpx import ASGITransport

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def reset_storage_fixture() -> None:
    """Reset storage before each test."""
    from aef_adapters.projection_stores import reset_projection_store
    from aef_adapters.projections import reset_projection_manager

    reset_storage()
    reset_projection_store()
    reset_projection_manager()
    clear_events()


async def create_test_workflow(workflow_id: str = "test-wf-1") -> WorkflowAggregate:
    """Create a test workflow and save it, updating projections."""
    from aef_adapters.projections import get_projection_manager

    repo = get_workflow_repository()
    command = CreateWorkflowCommand(
        aggregate_id=workflow_id,
        name="Test Workflow",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.STANDARD,
        repository_url="https://github.com/test/test",
        phases=[
            PhaseDefinition(
                phase_id="phase-1",
                name="Research Phase",
                order=1,
                description="Research phase",
            ),
            PhaseDefinition(
                phase_id="phase-2",
                name="Planning Phase",
                order=2,
                description="Planning phase",
            ),
        ],
    )
    workflow = WorkflowAggregate()
    workflow._handle_command(command)
    await repo.save(workflow)

    # Dispatch event to projections so read models are updated
    manager = get_projection_manager()
    await manager.dispatch_event(
        "WorkflowCreated",
        {
            "workflow_id": workflow_id,
            "name": "Test Workflow",
            "workflow_type": "research",
            "classification": "standard",
            "status": "pending",
            "phases": [
                {"phase_id": "phase-1", "name": "Research Phase", "order": 1},
                {"phase_id": "phase-2", "name": "Planning Phase", "order": 2},
            ],
        },
    )

    return workflow


async def create_test_session(
    session_id: str,
    workflow_id: str,
    phase_id: str,
    status: SessionStatus = SessionStatus.COMPLETED,
) -> AgentSessionAggregate:
    """Create a test session and save it, updating projections."""
    from aef_adapters.projections import get_projection_manager

    repo = get_session_repository()
    session = AgentSessionAggregate()

    # Start session
    session._handle_command(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            agent_provider="mock",
            agent_model="mock-model",
        )
    )

    # Record an operation
    session._handle_command(
        RecordOperationCommand(
            aggregate_id=session_id,
            operation_id="op-1",
            operation_type=OperationType.AGENT_REQUEST,
            timestamp=datetime.now(UTC),
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            duration_seconds=1.0,
        )
    )

    # Complete session
    session._handle_command(
        CompleteSessionCommand(
            aggregate_id=session_id,
            status=status,
        )
    )

    await repo.save(session)

    # Dispatch events to projections
    manager = get_projection_manager()
    await manager.dispatch_event(
        "SessionStarted",
        {
            "session_id": session_id,
            "workflow_id": workflow_id,
            "phase_id": phase_id,
            "agent_provider": "mock",
            "agent_model": "mock-model",
        },
    )
    await manager.dispatch_event(
        "SessionCompleted",
        {
            "session_id": session_id,
            "workflow_id": workflow_id,
            "phase_id": phase_id,
            "status": status.value,
            "total_tokens": 150,
            "total_cost_usd": "0.0015",
        },
    )

    return session


async def create_test_artifact(
    artifact_id: str,
    workflow_id: str,
    phase_id: str,
) -> ArtifactAggregate:
    """Create a test artifact and save it, updating projections."""
    from aef_adapters.projections import get_projection_manager

    repo = get_artifact_repository()
    artifact = ArtifactAggregate()

    artifact._handle_command(
        CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            artifact_type=ArtifactType.RESEARCH_SUMMARY,
            content="# Research Summary\n\nThis is test content.",
            title="Test Artifact",
        )
    )

    await repo.save(artifact)

    # Dispatch event to projections
    manager = get_projection_manager()
    await manager.dispatch_event(
        "ArtifactCreated",
        {
            "artifact_id": artifact_id,
            "workflow_id": workflow_id,
            "phase_id": phase_id,
            "artifact_type": "research_summary",
            "title": "Test Artifact",
            "content_length": len("# Research Summary\n\nThis is test content."),
        },
    )

    return artifact


# =============================================================================
# ROOT & HEALTH
# =============================================================================


class TestRootEndpoints:
    """Test root and health endpoints."""

    @pytest.mark.asyncio
    async def test_root(self, client: httpx.AsyncClient) -> None:
        """Test root endpoint."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "AEF Dashboard API"
        assert data["docs"] == "/docs"

    @pytest.mark.asyncio
    async def test_health(self, client: httpx.AsyncClient) -> None:
        """Test health check endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


# =============================================================================
# WORKFLOW ENDPOINTS
# =============================================================================


class TestWorkflowEndpoints:
    """Test workflow API endpoints."""

    @pytest.mark.asyncio
    async def test_list_workflows_empty(self, client: httpx.AsyncClient) -> None:
        """Test listing workflows when none exist."""
        response = await client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert data["workflows"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_workflows(self, client: httpx.AsyncClient) -> None:
        """Test listing workflows."""
        await create_test_workflow("wf-1")
        await create_test_workflow("wf-2")

        response = await client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["workflows"]) == 2

    @pytest.mark.asyncio
    async def test_list_workflows_pagination(self, client: httpx.AsyncClient) -> None:
        """Test workflow list pagination."""
        for i in range(5):
            await create_test_workflow(f"wf-{i}")

        response = await client.get("/api/workflows?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["workflows"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2

    @pytest.mark.asyncio
    async def test_get_workflow(self, client: httpx.AsyncClient) -> None:
        """Test getting a single workflow."""
        await create_test_workflow("test-wf-1")

        response = await client.get("/api/workflows/test-wf-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-wf-1"
        assert data["name"] == "Test Workflow"
        assert len(data["phases"]) == 2

    @pytest.mark.asyncio
    async def test_get_workflow_not_found(self, client: httpx.AsyncClient) -> None:
        """Test getting non-existent workflow."""
        response = await client.get("/api/workflows/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Execution history projection not yet implemented")
    async def test_get_workflow_history(self, client: httpx.AsyncClient) -> None:
        """Test getting workflow execution history."""
        await create_test_workflow("test-wf-1")
        await create_test_session("sess-1", "test-wf-1", "phase-1")
        await create_test_session("sess-2", "test-wf-1", "phase-2")

        response = await client.get("/api/workflows/test-wf-1/history")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "test-wf-1"
        assert data["total_executions"] == 1
        assert len(data["executions"]) == 1
        assert data["executions"][0]["total_tokens"] == 300  # 150 * 2 sessions


# =============================================================================
# SESSION ENDPOINTS
# =============================================================================


class TestSessionEndpoints:
    """Test session API endpoints."""

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, client: httpx.AsyncClient) -> None:
        """Test listing sessions when none exist."""
        response = await client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_sessions(self, client: httpx.AsyncClient) -> None:
        """Test listing sessions."""
        await create_test_workflow("wf-1")
        await create_test_session("sess-1", "wf-1", "phase-1")
        await create_test_session("sess-2", "wf-1", "phase-2")

        response = await client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_by_workflow(self, client: httpx.AsyncClient) -> None:
        """Test filtering sessions by workflow."""
        await create_test_workflow("wf-1")
        await create_test_workflow("wf-2")
        await create_test_session("sess-1", "wf-1", "phase-1")
        await create_test_session("sess-2", "wf-2", "phase-1")

        response = await client.get("/api/sessions?workflow_id=wf-1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["workflow_id"] == "wf-1"

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Session operations projection not yet implemented")
    async def test_get_session(self, client: httpx.AsyncClient) -> None:
        """Test getting a single session."""
        await create_test_workflow("wf-1")
        await create_test_session("sess-1", "wf-1", "phase-1")

        response = await client.get("/api/sessions/sess-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "sess-1"
        assert data["workflow_id"] == "wf-1"
        assert data["total_tokens"] == 150
        assert len(data["operations"]) == 1

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, client: httpx.AsyncClient) -> None:
        """Test getting non-existent session."""
        response = await client.get("/api/sessions/nonexistent")
        assert response.status_code == 404


# =============================================================================
# ARTIFACT ENDPOINTS
# =============================================================================


class TestArtifactEndpoints:
    """Test artifact API endpoints."""

    @pytest.mark.asyncio
    async def test_list_artifacts_empty(self, client: httpx.AsyncClient) -> None:
        """Test listing artifacts when none exist."""
        response = await client.get("/api/artifacts")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_artifacts(self, client: httpx.AsyncClient) -> None:
        """Test listing artifacts."""
        await create_test_workflow("wf-1")
        await create_test_artifact("art-1", "wf-1", "phase-1")
        await create_test_artifact("art-2", "wf-1", "phase-2")

        response = await client.get("/api/artifacts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_list_artifacts_by_workflow(self, client: httpx.AsyncClient) -> None:
        """Test filtering artifacts by workflow."""
        await create_test_workflow("wf-1")
        await create_test_workflow("wf-2")
        await create_test_artifact("art-1", "wf-1", "phase-1")
        await create_test_artifact("art-2", "wf-2", "phase-1")

        response = await client.get("/api/artifacts?workflow_id=wf-1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["workflow_id"] == "wf-1"

    @pytest.mark.asyncio
    async def test_get_artifact_without_content(self, client: httpx.AsyncClient) -> None:
        """Test getting artifact without content."""
        await create_test_workflow("wf-1")
        await create_test_artifact("art-1", "wf-1", "phase-1")

        response = await client.get("/api/artifacts/art-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "art-1"
        assert data["content"] is None  # Not included by default

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Artifact content storage not yet implemented in projection")
    async def test_get_artifact_with_content(self, client: httpx.AsyncClient) -> None:
        """Test getting artifact with content."""
        await create_test_workflow("wf-1")
        await create_test_artifact("art-1", "wf-1", "phase-1")

        response = await client.get("/api/artifacts/art-1?include_content=true")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "art-1"
        assert "Research Summary" in data["content"]

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Artifact content storage not yet implemented in projection")
    async def test_get_artifact_content_only(self, client: httpx.AsyncClient) -> None:
        """Test getting artifact content only."""
        await create_test_workflow("wf-1")
        await create_test_artifact("art-1", "wf-1", "phase-1")

        response = await client.get("/api/artifacts/art-1/content")
        assert response.status_code == 200
        data = response.json()
        assert data["artifact_id"] == "art-1"
        assert "Research Summary" in data["content"]

    @pytest.mark.asyncio
    async def test_get_artifact_not_found(self, client: httpx.AsyncClient) -> None:
        """Test getting non-existent artifact."""
        response = await client.get("/api/artifacts/nonexistent")
        assert response.status_code == 404


# =============================================================================
# METRICS ENDPOINTS
# =============================================================================


class TestMetricsEndpoints:
    """Test metrics API endpoints."""

    @pytest.mark.asyncio
    async def test_metrics_empty(self, client: httpx.AsyncClient) -> None:
        """Test metrics when no data exists."""
        response = await client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_workflows"] == 0
        assert data["total_sessions"] == 0
        assert data["total_artifacts"] == 0

    @pytest.mark.asyncio
    async def test_metrics_with_data(self, client: httpx.AsyncClient) -> None:
        """Test metrics with workflow data."""
        await create_test_workflow("wf-1")
        await create_test_session("sess-1", "wf-1", "phase-1")
        await create_test_artifact("art-1", "wf-1", "phase-1")

        response = await client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_workflows"] == 1
        assert data["total_sessions"] == 1
        assert data["total_artifacts"] == 1
        assert data["total_tokens"] == 150

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Per-workflow phase metrics not yet implemented")
    async def test_metrics_for_workflow(self, client: httpx.AsyncClient) -> None:
        """Test metrics for specific workflow."""
        await create_test_workflow("wf-1")
        await create_test_session("sess-1", "wf-1", "phase-1")
        await create_test_session("sess-2", "wf-1", "phase-2")
        await create_test_artifact("art-1", "wf-1", "phase-1")

        response = await client.get("/api/metrics?workflow_id=wf-1")
        assert response.status_code == 200
        data = response.json()
        assert data["total_workflows"] == 1
        assert data["total_sessions"] == 2
        assert len(data["phases"]) == 2
        assert data["phases"][0]["phase_name"] == "Research Phase"


# =============================================================================
# EVENTS ENDPOINTS
# =============================================================================


class TestEventsEndpoints:
    """Test events API endpoints."""

    @pytest.mark.asyncio
    async def test_get_recent_events_empty(self, client: httpx.AsyncClient) -> None:
        """Test getting recent events when none exist."""
        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_recent_events(self, client: httpx.AsyncClient) -> None:
        """Test getting recent events."""
        push_event("workflow_started", {"workflow_id": "wf-1"})
        push_event("phase_started", {"workflow_id": "wf-1", "phase_id": "p-1"})

        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["event_type"] == "workflow_started"

    @pytest.mark.asyncio
    async def test_get_recent_events_filtered(self, client: httpx.AsyncClient) -> None:
        """Test filtering events by workflow."""
        push_event("workflow_started", {"workflow_id": "wf-1"})
        push_event("workflow_started", {"workflow_id": "wf-2"})

        response = await client.get("/api/events/recent?workflow_id=wf-1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["data"]["workflow_id"] == "wf-1"

    @pytest.mark.asyncio
    async def test_push_event(self, client: httpx.AsyncClient) -> None:
        """Test pushing a custom event."""
        response = await client.post("/api/events/push?event_type=test_event&workflow_id=wf-1")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify event was pushed
        response = await client.get("/api/events/recent")
        data = response.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "test_event"


# =============================================================================
# EXECUTION ENDPOINTS (F7.6 Regression Tests)
# =============================================================================


class TestExecutionEndpoints:
    """REGRESSION: Test execution API endpoints for F7.6 Workflow Execution Model."""

    @pytest.mark.asyncio
    async def test_list_workflow_runs_empty(self, client: httpx.AsyncClient) -> None:
        """REGRESSION: GET /api/workflows/{id}/runs returns empty list when no runs."""
        from aef_adapters.projections import get_projection_manager

        manager = get_projection_manager()

        # Create a workflow first
        workflow_id = "test-workflow-for-runs"
        await manager.dispatch_event(
            "WorkflowCreated",
            {
                "workflow_id": workflow_id,
                "name": "Test Workflow",
                "workflow_type": "research",
                "classification": "development",
                "phases": [],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

        response = await client.get(f"/api/workflows/{workflow_id}/runs")
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data
        assert data["runs"] == []
        assert data["total"] == 0
        assert data["workflow_id"] == workflow_id
        assert "workflow_name" in data

    @pytest.mark.asyncio
    async def test_list_workflow_runs_not_found(self, client: httpx.AsyncClient) -> None:
        """REGRESSION: GET /api/workflows/{id}/runs returns 404 for unknown workflow."""
        response = await client.get("/api/workflows/nonexistent-workflow/runs")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, client: httpx.AsyncClient) -> None:
        """REGRESSION: GET /api/executions/{id} returns 404 for unknown execution."""
        response = await client.get("/api/executions/nonexistent-execution")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_session_response_schema_has_execution_id(
        self, client: httpx.AsyncClient
    ) -> None:
        """REGRESSION: Session response schema includes execution_id field."""
        from aef_adapters.projections import get_projection_manager

        manager = get_projection_manager()

        # Create a session
        session_id = "test-session-with-exec"
        await manager.dispatch_event(
            "SessionStarted",
            {
                "aggregate_id": session_id,
                "session_id": session_id,
                "workflow_id": "test-workflow",
                "execution_id": "test-execution",
                "phase_id": "phase-1",
                "agent_provider": "claude",
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

        response = await client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        # Verify execution_id field exists
        assert "execution_id" in data[0]
