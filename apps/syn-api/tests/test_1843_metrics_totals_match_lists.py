"""#1843 items 1 and 3: a /metrics count equals the total of the list it summarises.

Seeded through the handlers of EVERY read model the events reach, then read
over HTTP, because the defect was two surfaces answering one question from two
definitions: each read model was internally right.

- Sessions: /metrics counted every session id the observability lane saw emit
  an event, delegates included; /sessions lists the sessions the domain
  started, including ones that failed before the agent emitted anything.
- Artifacts (item 2): /metrics added one per ``ArtifactCreated`` to a running
  counter on one global row; /artifacts counts the rows of the artifact list.
- Failed executions: /metrics added one per ``WorkflowFailed`` event to a
  running counter; /executions tallies each execution once by its current
  status.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.agent_sessions import CanonicalTotals

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

STARTED_AT = "2026-11-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


class _ObservedSessions:
    """The observability lane: it saw three session ids emit events.

    ``sess-a``, ``sess-c`` and the delegate ``sess-delegate`` emitted events;
    ``sess-b`` and ``sess-d`` failed before their agents emitted anything. The
    delegate has no SessionStarted, so the session list has no row for it.
    """

    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        return CanonicalTotals(sessions=3)


class _NoExecutionCosts:
    """No ``ExecutionCost`` rows: /metrics reads its money from them (#897)."""

    async def list_all(self, limit: int = 500) -> list[object]:
        return []

    async def list_for_ids(self, execution_ids: set[str]) -> list[object]:
        return []


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    from syn_api._wiring import ensure_connected
    from syn_api.main import create_app
    from syn_api.routes import metrics

    await ensure_connected()
    monkeypatch.setattr(metrics, "get_canonical_usage_query", _ObservedSessions)
    monkeypatch.setattr(metrics, "get_execution_cost_query", _NoExecutionCosts)
    monkeypatch.setattr(metrics, "_workflow_execution_ids", _no_execution_ids)
    monkeypatch.setattr(metrics, "_build_phase_metrics", _no_phases)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _no_execution_ids(workflow_id: str) -> set[str]:
    return set()


async def _no_phases(workflow_id: str, execution_ids: set[str]) -> list[object]:
    return []


async def _start_session(session_id: str, workflow_id: str) -> None:
    from syn_api._wiring import get_projection_mgr

    event = {
        "session_id": session_id,
        "workflow_id": workflow_id,
        "execution_id": f"exec-of-{session_id}",
        "agent_provider": "claude",
        "started_at": STARTED_AT,
    }
    await get_projection_mgr().session_list.on_session_started(event)


async def _seed_sessions() -> None:
    await _start_session("sess-a", "wf-a")
    await _start_session("sess-b", "wf-a")
    await _start_session("sess-c", "wf-b")
    await _start_session("sess-d", "wf-b")


async def test_total_sessions_is_the_session_list_total(client: AsyncClient) -> None:
    await _seed_sessions()

    metrics = (await client.get("/metrics")).json()
    sessions = (await client.get("/sessions")).json()

    assert sessions["total"] == 4
    assert metrics["total_sessions"] == sessions["total"]


async def test_total_sessions_narrows_like_the_session_list(client: AsyncClient) -> None:
    await _seed_sessions()

    metrics = (await client.get("/metrics", params={"workflow_id": "wf-a"})).json()
    sessions = (await client.get("/sessions", params={"workflow_id": "wf-a"})).json()

    # The observability lane would have said 3 here as well: it is not asked
    # about workflows, only executions, and sees the delegate.
    assert sessions["total"] == 2
    assert metrics["total_sessions"] == sessions["total"]


async def _execution(execution_id: str, *fates: str) -> None:
    """Start an execution and deliver its terminal events to the execution list."""
    from syn_api._wiring import get_projection_mgr

    manager = get_projection_mgr()
    executions = manager.workflow_execution_list
    started = {
        "execution_id": execution_id,
        "workflow_id": "wf-a",
        "workflow_name": "wf-a",
        "started_at": STARTED_AT,
    }
    await executions.on_workflow_execution_started(started)
    for fate in fates:
        event = {"execution_id": execution_id}
        if fate == "failed":
            await executions.on_workflow_failed(event)
        elif fate == "completed":
            await executions.on_workflow_completed(event)


async def test_failed_workflows_is_the_execution_list_failed_count(client: AsyncClient) -> None:
    # Failed, resumed, completed: one completed execution, not a failure too.
    await _execution("exec-resumed", "failed", "completed")
    # Two WorkflowFailed events for one execution: one failed execution.
    await _execution("exec-failed-twice", "failed", "failed")
    await _execution("exec-failed", "failed")
    await _execution("exec-ok", "completed")

    metrics = (await client.get("/metrics")).json()
    executions = (await client.get("/executions")).json()

    assert executions["status_counts"]["failed"] == 2
    assert metrics["failed_workflows"] == executions["status_counts"]["failed"]
    assert metrics["execution_status_counts"]["failed"] == metrics["failed_workflows"]
    assert executions["status_counts"]["completed"] == 2
    assert metrics["completed_workflows"] == executions["status_counts"]["completed"]


async def test_a_failure_the_counter_never_applied_is_still_counted(
    client: AsyncClient,
) -> None:
    """The live direction (715 beside 716): a failure only the list holds.

    A lost read-modify-write on the counters' single global row, or a counter
    row older than the list's rebuild, leaves the failure in the list alone.
    """
    from syn_api._wiring import get_projection_mgr

    await _execution("exec-failed", "failed")
    executions = get_projection_mgr().workflow_execution_list
    await executions.on_workflow_execution_started(
        {"execution_id": "exec-lost", "workflow_id": "wf-a", "started_at": STARTED_AT}
    )
    await executions.on_workflow_failed({"execution_id": "exec-lost"})

    metrics = (await client.get("/metrics")).json()
    listed = (await client.get("/executions")).json()

    assert listed["status_counts"]["failed"] == 2
    assert metrics["failed_workflows"] == listed["status_counts"]["failed"]


async def _create_artifact(artifact_id: str, workflow_id: str) -> None:
    from syn_api._wiring import get_projection_mgr

    event = {
        "artifact_id": artifact_id,
        "workflow_id": workflow_id,
        "artifact_type": "code",
        "title": artifact_id,
        "size_bytes": 10,
        "created_at": STARTED_AT,
    }
    await get_projection_mgr().artifact_list.on_artifact_created(event)


async def test_total_artifacts_is_the_artifact_list_total(client: AsyncClient) -> None:
    """The live direction (28907 beside 28914): artifacts the counter never applied.

    The dashboard counter is given one increment it kept, the list three rows,
    so the two read models disagree and the test says which one /metrics reads.
    """
    from syn_api._wiring import get_projection_mgr

    await get_projection_mgr().dashboard_metrics.on_artifact_created(
        {"artifact_id": "art-a", "size_bytes": 10}
    )
    await _create_artifact("art-a", "wf-a")
    await _create_artifact("art-b", "wf-a")
    await _create_artifact("art-c", "wf-b")

    metrics = (await client.get("/metrics")).json()
    artifacts = (await client.get("/artifacts", params={"page_size": 1})).json()

    assert artifacts["total"] == 3
    assert metrics["total_artifacts"] == artifacts["total"]


async def test_total_artifacts_narrows_like_the_artifact_list(client: AsyncClient) -> None:
    await _create_artifact("art-a", "wf-a")
    await _create_artifact("art-b", "wf-a")
    await _create_artifact("art-c", "wf-b")

    metrics = (await client.get("/metrics", params={"workflow_id": "wf-a"})).json()
    artifacts = (await client.get("/artifacts", params={"workflow_id": "wf-a"})).json()

    assert artifacts["total"] == 2
    assert metrics["total_artifacts"] == artifacts["total"]
