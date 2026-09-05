"""Tests for syn_api.routes.executions — list, get, get_detail, list_active."""

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from syn_api.types import Err, Ok
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")


#: Calling the endpoint function directly bypasses FastAPI, so every parameter
#: left out arrives as the ``Query(...)`` sentinel rather than as its default.
#: Spelling the whole signature once here means adding a parameter is one edit,
#: not one per call site.
_LIST_ARGS: Mapping[str, object] = {
    "status": None,
    "statuses": None,
    "started_after": None,
    "started_before": None,
    "q": None,
    "page": 1,
    "page_size": 50,
}


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _seed_execution(
    exec_id: str,
    workflow_id: str,
    workflow_name: str,
    status: str = "running",
    total_phases: int = 2,
) -> None:
    """Seed an execution into both projection stores."""
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()

    # Seed into execution list projection
    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        exec_id,
        {
            "workflow_execution_id": exec_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": status,
            "started_at": "2026-03-23T10:00:00Z",
            "completed_at": None if status == "running" else "2026-03-23T10:05:00Z",
            "completed_phases": 0 if status == "running" else total_phases,
            "total_phases": total_phases,
            "total_tokens": 1000,
            "total_cost_usd": "0.05",
            "tool_call_count": 5,
            "error_message": None,
        },
    )

    # Seed into execution detail projection
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "execution_id": exec_id,
            "workflow_execution_id": exec_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": status,
            "started_at": "2026-03-23T10:00:00Z",
            "completed_at": None if status == "running" else "2026-03-23T10:05:00Z",
            "total_input_tokens": 500,
            "total_output_tokens": 500,
            "total_cost_usd": "0.05",
            "total_duration_seconds": 30.0,
            "artifact_ids": [],
            "error_message": None,
            "phases": [],
        },
    )


async def test_list_executions_with_data():
    """Seed two executions, verify list_ returns both."""
    from syn_api.routes.executions import list_

    await _seed_execution("exec-1", "wf-1", "Workflow A")
    await _seed_execution("exec-2", "wf-1", "Workflow A", status="completed")

    result = await list_()
    assert isinstance(result, Ok)
    assert len(result.value) == 2
    ids = {e.workflow_execution_id for e in result.value}
    assert ids == {"exec-1", "exec-2"}


async def test_list_executions_filter_by_workflow():
    """Seed executions for two workflows, filter by one."""
    from syn_api.routes.executions import list_

    await _seed_execution("exec-a", "wf-1", "Workflow A")
    await _seed_execution("exec-b", "wf-2", "Workflow B")
    await _seed_execution("exec-c", "wf-1", "Workflow A", status="completed")

    result = await list_(workflow_id="wf-1")
    assert isinstance(result, Ok)
    assert len(result.value) == 2
    assert all(e.workflow_id == "wf-1" for e in result.value)


async def test_get_execution():
    """Seed an execution, get by ID."""
    from syn_api.routes.executions import get

    await _seed_execution("exec-get-1", "wf-1", "Workflow A")

    result = await get("exec-get-1")
    assert isinstance(result, Ok)
    assert result.value.workflow_execution_id == "exec-get-1"
    assert result.value.workflow_id == "wf-1"
    assert result.value.workflow_name == "Workflow A"
    assert result.value.total_input_tokens == 500
    assert result.value.total_output_tokens == 500


async def test_get_execution_not_found():
    """Get nonexistent execution returns Err."""
    from syn_api.routes.executions import get

    result = await get("nonexistent-id")
    assert isinstance(result, Err)


async def test_get_detail():
    """Seed an execution, get full detail."""
    from syn_api.routes.executions import get_detail

    await _seed_execution("exec-detail-1", "wf-1", "Workflow A")

    result = await get_detail("exec-detail-1")
    assert isinstance(result, Ok)
    assert result.value.workflow_execution_id == "exec-detail-1"
    assert result.value.workflow_id == "wf-1"
    assert result.value.phases == []


async def test_get_detail_not_found():
    """Get detail for nonexistent execution returns Err."""
    from syn_api.routes.executions import get_detail

    result = await get_detail("nonexistent-id")
    assert isinstance(result, Err)


async def _seed_execution_with_running_phase(
    exec_id: str, workflow_id: str, phase_started_at: str
) -> None:
    """Seed an execution with a single RUNNING phase, exactly as the
    projection would leave it mid-flight: duration_seconds still 0.0
    (nothing has completed it yet) and no completed_at.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()

    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "execution_id": exec_id,
            "workflow_execution_id": exec_id,
            "workflow_id": workflow_id,
            "workflow_name": "Workflow A",
            "status": "running",
            "started_at": phase_started_at,
            "completed_at": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "total_duration_seconds": 0.0,
            "artifact_ids": [],
            "error_message": None,
            "phases": [
                {
                    "workflow_phase_id": "phase-1",
                    "name": "Phase 1",
                    "status": "running",
                    "session_id": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "duration_seconds": 0.0,
                    "started_at": phase_started_at,
                    "completed_at": None,
                    "error_message": None,
                }
            ],
        },
    )


async def test_get_detail_running_phase_duration_advances_between_reads():
    """A RUNNING phase's duration_seconds must be computed live, not read
    back as the 0.0 the projection seeded it with.

    Regression test for the 2026-09-01 incident: six healthy workflow runs
    were cancelled because a running phase's duration looked frozen. A test
    that only asserted ``duration_seconds is not None`` would already pass
    today against the stored ``0.0`` -- so this asserts the value ADVANCES
    between two reads of the same still-running phase, which is only
    possible if it is computed against the wall clock at read time.
    """
    from syn_api.routes.executions import get_detail

    started_at = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    await _seed_execution_with_running_phase("exec-running-phase", "wf-1", started_at)

    first = await get_detail("exec-running-phase")
    assert isinstance(first, Ok)
    first_duration = first.value.phases[0].duration_seconds
    assert first_duration is not None
    assert first_duration > 0.0

    await asyncio.sleep(0.05)

    second = await get_detail("exec-running-phase")
    assert isinstance(second, Ok)
    second_duration = second.value.phases[0].duration_seconds
    assert second_duration is not None
    assert second_duration > first_duration


async def _seed_execution_detail_with_phases(
    exec_id: str,
    phases: list[dict],
    *,
    status: str = "running",
    started_at: str = "2026-03-23T10:00:00Z",
    stored_total_duration: float = 0.0,
) -> None:
    """Seed only the DETAIL projection, with phases given verbatim.

    ``stored_total_duration`` is the projection's own accumulated total, which
    only ever counts phases that have COMPLETED. Tests below assert the API
    total does NOT come from it.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "execution_id": exec_id,
            "workflow_execution_id": exec_id,
            "workflow_id": "wf-1",
            "workflow_name": "Workflow A",
            "status": status,
            "started_at": started_at,
            "completed_at": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "total_duration_seconds": stored_total_duration,
            "artifact_ids": [],
            "error_message": None,
            "phases": phases,
        },
    )


def _phase(
    phase_id: str,
    status: str,
    *,
    started_at: str | None = None,
    completed_at: str | None = None,
    duration_seconds: float | None = None,
    session_id: str | None = None,
) -> dict:
    """A phase row shaped exactly as the projection stores it."""
    return {
        "workflow_phase_id": phase_id,
        "name": phase_id,
        "status": status,
        "session_id": session_id,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "total_tokens": 0,
        "duration_seconds": duration_seconds,
        "started_at": started_at,
        "completed_at": completed_at,
        "error_message": None,
    }


async def test_list_reports_a_live_duration_for_a_running_execution():
    """The LIST surface must answer "how long has this been running", not None.

    It required BOTH timestamps, and a running execution has no completed_at by
    definition -- so every running execution reported no duration in the list
    while its detail view reported a live one. The two surfaces disagreed about
    the same execution.
    """
    from syn_api.routes.executions import queries

    started_at = (datetime.now(UTC) - timedelta(seconds=420)).isoformat()
    await _seed_execution("exec-live-list", "wf-1", "Workflow A")
    manager = queries.get_projection_mgr()
    row = await manager.workflow_execution_list._store.get("workflow_executions", "exec-live-list")
    row["started_at"] = started_at
    await manager.workflow_execution_list._store.save("workflow_executions", "exec-live-list", row)

    response = await queries.list_executions_endpoint(**_LIST_ARGS)
    summary = next(e for e in response.executions if e.workflow_execution_id == "exec-live-list")
    assert summary.duration_seconds is not None
    # ~420s could not have arisen from the old code, which returned None here,
    # nor from any stored value: nothing in the fixture holds 420.
    assert summary.duration_seconds == pytest.approx(420.0, abs=5.0)
    assert summary.duration_display == "7m"


async def test_list_reports_unknown_rather_than_zero_for_an_unstarted_execution():
    """A pending execution has no start. Unknown, and it must say so."""
    from syn_api.routes.executions import queries

    await _seed_execution("exec-pending-list", "wf-1", "Workflow A")
    manager = queries.get_projection_mgr()
    row = await manager.workflow_execution_list._store.get(
        "workflow_executions", "exec-pending-list"
    )
    row["status"] = "pending"
    row["started_at"] = None
    await manager.workflow_execution_list._store.save(
        "workflow_executions", "exec-pending-list", row
    )

    response = await queries.list_executions_endpoint(**_LIST_ARGS)
    summary = next(e for e in response.executions if e.workflow_execution_id == "exec-pending-list")
    assert summary.duration_seconds is None
    assert summary.duration_display == "\u2014"


async def test_pending_phase_duration_is_unknown_not_zero():
    """A phase that has not started reported 0.0 -- "finished instantly"."""
    from syn_api.routes.executions import get_detail

    await _seed_execution_detail_with_phases("exec-pending-phase", [_phase("phase-1", "pending")])

    result = await get_detail("exec-pending-phase")
    assert isinstance(result, Ok)
    assert result.value.phases[0].duration_seconds is None


async def test_execution_total_includes_the_phase_still_running():
    """The total is presented as final while excluding the live phase.

    The projection's accumulated ``total_duration_seconds`` only grows when a
    phase COMPLETES, so an execution 400 seconds into its second phase reported
    the 10 seconds its first phase took. Seeded here as exactly that.
    """
    from syn_api.routes.executions import get_detail

    started_at = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    await _seed_execution_detail_with_phases(
        "exec-live-total",
        [
            _phase(
                "phase-1",
                "completed",
                started_at="2026-03-23T10:00:00Z",
                completed_at="2026-03-23T10:00:10Z",
                duration_seconds=10.0,
            ),
            _phase("phase-2", "running", started_at=started_at),
        ],
        stored_total_duration=10.0,
    )

    result = await get_detail("exec-live-total")
    assert isinstance(result, Ok)
    total = result.value.total_duration_seconds
    assert total is not None
    # 410 = the completed phase's 10s plus the running phase's live 400s. The
    # stored total is 10.0, so this value cannot have been read from it.
    assert total == pytest.approx(410.0, abs=5.0)
    assert result.value.unknown_duration_phase_count == 0


async def test_execution_total_says_how_many_phases_it_could_not_count():
    """A total that silently omits phases is a lower bound wearing a total's
    clothes -- the #890 cost defect, in the duration column."""
    from syn_api.routes.executions import get_detail

    await _seed_execution_detail_with_phases(
        "exec-partial-total",
        [
            _phase(
                "phase-1",
                "completed",
                started_at="2026-03-23T10:00:00Z",
                completed_at="2026-03-23T10:00:10Z",
                duration_seconds=10.0,
            ),
            # Failed mid-flight with nothing recorded: genuinely unknown.
            _phase("phase-2", "failed", started_at="2026-03-23T10:00:10Z"),
        ],
        status="failed",
        stored_total_duration=10.0,
    )

    result = await get_detail("exec-partial-total")
    assert isinstance(result, Ok)
    assert result.value.total_duration_seconds == 10.0
    assert result.value.unknown_duration_phase_count == 1


async def test_execution_total_is_unknown_when_no_phase_can_be_measured():
    from syn_api.routes.executions import get_detail

    await _seed_execution_detail_with_phases(
        "exec-unknown-total", [_phase("phase-1", "pending"), _phase("phase-2", "pending")]
    )

    result = await get_detail("exec-unknown-total")
    assert isinstance(result, Ok)
    assert result.value.total_duration_seconds is None
    assert result.value.unknown_duration_phase_count == 2


async def test_http_response_carries_the_live_total_and_its_coverage():
    """The hop that drops values: ExecutionDetailFull -> ExecutionDetailResponse.

    Both fields are resolved two layers down and re-listed by hand at the
    response constructor, which is exactly where a correct value gets left
    behind. Asserted on the response model the endpoint actually returns.
    """
    from syn_api.routes.executions.queries import get_execution_endpoint

    started_at = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    await _seed_execution_detail_with_phases(
        "exec-http-total",
        [
            _phase(
                "phase-1",
                "completed",
                started_at="2026-03-23T10:00:00Z",
                completed_at="2026-03-23T10:00:10Z",
                duration_seconds=10.0,
            ),
            _phase("phase-2", "running", started_at=started_at),
            _phase("phase-3", "pending"),
        ],
        stored_total_duration=10.0,
    )

    response = await get_execution_endpoint("exec-http-total")
    assert response.total_duration_seconds is not None
    assert response.total_duration_seconds == pytest.approx(410.0, abs=5.0)
    assert response.unknown_duration_phase_count == 1
    # And the phases the total was folded from agree with it, on this response.
    assert response.phases[0].duration_seconds == 10.0
    assert response.phases[1].duration_seconds == pytest.approx(400.0, abs=5.0)
    assert response.phases[2].duration_seconds is None


async def test_a_future_started_at_does_not_become_a_confident_zero():
    """Clock skew produced 0.0 -- "just started" for a phase of unknown age."""
    from syn_api.routes.executions import get_detail

    started_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    await _seed_execution_detail_with_phases(
        "exec-future-start", [_phase("phase-1", "running", started_at=started_at)]
    )

    result = await get_detail("exec-future-start")
    assert isinstance(result, Ok)
    assert result.value.phases[0].duration_seconds is None
    assert result.value.total_duration_seconds is None
    assert result.value.unknown_duration_phase_count == 1


async def test_a_malformed_started_at_does_not_become_a_confident_zero():
    from syn_api.routes.executions import get_detail

    await _seed_execution_detail_with_phases(
        "exec-bad-start", [_phase("phase-1", "running", started_at="not-a-timestamp")]
    )

    result = await get_detail("exec-bad-start")
    assert isinstance(result, Ok)
    assert result.value.phases[0].duration_seconds is None
    assert result.value.unknown_duration_phase_count == 1


async def test_list_active():
    """Seed running + completed executions, list_active returns only running."""
    from syn_api.routes.executions import list_active

    await _seed_execution("exec-running", "wf-1", "Workflow A", status="running")
    await _seed_execution("exec-done", "wf-1", "Workflow A", status="completed")
    await _seed_execution("exec-failed", "wf-2", "Workflow B", status="failed")

    result = await list_active()
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].workflow_execution_id == "exec-running"
    assert result.value[0].status == "running"


# -- Regression tests for #1077 (list endpoint N+1 / duplicate enrichment) ----


@dataclass
class _CountingExecutionCostProjection:
    """Stands in for the real execution_cost projection.

    ``get_execution_cost`` raises so any code path that still loops per
    execution id (the pre-#1077 behavior) fails loudly instead of silently
    working via the slow path. ``list_costs_for_ids`` records every call it
    receives so a test can assert it was called exactly once, covering every
    requested id.
    """

    costs_by_id: dict[str, ExecutionCost]
    list_calls: list[list[str]] = field(default_factory=list)

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        raise AssertionError(
            f"get_execution_cost({execution_id!r}) was called - the list path "
            "must use the batched list_costs_for_ids instead of a per-execution "
            "loop (issue #1077)"
        )

    async def list_costs_for_ids(self, execution_ids: list[str]) -> dict[str, ExecutionCost]:
        self.list_calls.append(list(execution_ids))
        return {eid: c for eid, c in self.costs_by_id.items() if eid in execution_ids}


@dataclass
class _StubProjectionManagerForEnrichment:
    execution_cost: _CountingExecutionCostProjection


async def test_load_execution_enrichment_batches_across_ids():
    """Regression for #1077: enrichment must come from one batched call to
    ``list_costs_for_ids`` covering every requested id, not one
    ``get_execution_cost`` round trip per execution (up to ~6 sequential
    queries each, per the issue's own investigation).
    """
    from syn_api.routes.executions.queries import _load_execution_enrichment

    costs = {
        "exec-a": ExecutionCost(
            execution_id="exec-a",
            total_cost_usd=Decimal("1.50"),
            input_tokens=5,
            output_tokens=5,
        ),
        "exec-b": ExecutionCost(
            execution_id="exec-b",
            total_cost_usd=Decimal("2.50"),
            input_tokens=7,
            output_tokens=3,
        ),
    }
    stub = _CountingExecutionCostProjection(costs_by_id=costs)
    manager = _StubProjectionManagerForEnrichment(execution_cost=stub)

    enrichment = await _load_execution_enrichment(
        manager,  # pyright: ignore[reportArgumentType] - structural stub
        ["exec-a", "exec-b"],
    )

    assert len(stub.list_calls) == 1, (
        f"expected exactly one batched call for both ids, got {len(stub.list_calls)}: "
        f"{stub.list_calls}"
    )
    assert set(stub.list_calls[0]) == {"exec-a", "exec-b"}
    assert enrichment["exec-a"].total_cost_usd == Decimal("1.50")
    assert enrichment["exec-b"].total_cost_usd == Decimal("2.50")


async def test_list_executions_endpoint_loads_enrichment_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #1077: ``list_executions_endpoint`` fetched enrichment
    for the same execution ids twice in one request - once inside
    ``list_()``, once again directly - doubling every downstream cost
    round trip. This drives the real endpoint end-to-end and counts
    invocations of the enrichment loader: it must be called once per
    request, not once per page plus once more.
    """
    from syn_api.routes.executions import queries as executions_queries

    await _seed_execution("exec-once-a", "wf-1", "Workflow A")
    await _seed_execution("exec-once-b", "wf-1", "Workflow A")

    calls: list[list[str]] = []
    original = executions_queries._load_execution_enrichment

    async def _counting_enrichment(manager: object, execution_ids: list[str]) -> object:
        calls.append(list(execution_ids))
        return await original(manager, execution_ids)

    monkeypatch.setattr(executions_queries, "_load_execution_enrichment", _counting_enrichment)

    response = await executions_queries.list_executions_endpoint(**_LIST_ARGS)

    assert len(calls) == 1, (
        f"expected exactly one enrichment fetch for the whole request, got {len(calls)}: {calls}"
    )
    assert {e.workflow_execution_id for e in response.executions} == {
        "exec-once-a",
        "exec-once-b",
    }


# -- #1185: an execution must be traceable to the transcripts it produced ------
#
# The relation exists only in the capture observation on Lane 2: a phase's
# `session_id` is a uuid4 the HOST assigns, and the ids the AGENTS chose for
# themselves are a disjoint namespace. Nothing else in the system joins them.
#
# Every assertion below is made on `ExecutionDetailResponse`, the model the HTTP
# endpoint actually returns -- NOT on the intermediate `PhaseExecution`. The
# value is carried across two hand-listed constructors (`_map_phase_detail`,
# then `_map_phase_to_response`), and a hop that drops it satisfies any test
# that inspects the objects at either end.


def _capture_row(
    session_id: str,
    *,
    execution_id: str = "exec-capture",
    schema_version: int | None = None,
    **payload_overrides: object,
) -> dict:
    """One row exactly as ``AgentEventStore.query_by_execution`` returns it.

    FLATTENED, not nested. `query_execution_events` spreads the stored payload
    across the top level (`**json.loads(row["data"])`) while `query_session_events`
    nests it under `data`. Building the fixture in the wrong one of those two
    shapes is how the capture status route once certified a reader that reported
    every healthy row as UNKNOWN, so this mirrors the adapter it is standing in
    for and not the other one.

    The payload half is built through the real `CaptureObservationData`, so a
    renamed field fails here rather than silently serialising to nothing.
    """
    import json

    from syn_adapters.workspace_backends.agentic.capture_observation import (
        SESSION_CAPTURE_OBSERVATION,
        CaptureObservationData,
    )

    payload = json.loads(
        CaptureObservationData(
            state="captured",
            needs_backfill=False,
            reason=None,
            store_url="https://sessions.example.com",
            origin_environment="container",
            origin_deployment="syntropic137__development",
            partition="e-1/w-1",
        ).model_dump_json()
    )
    if schema_version is not None:
        payload["schema_version"] = schema_version
    payload.update(payload_overrides)
    return {
        "timestamp": "2026-03-23T10:00:05+00:00",
        "event_type": SESSION_CAPTURE_OBSERVATION,
        "session_id": session_id,
        "execution_id": execution_id,
        "phase_id": "p-1",
        **payload,
    }


@pytest.fixture
def _capture_rows(monkeypatch: pytest.MonkeyPatch):
    """Stand in for the event store the capture lookup reads from."""

    def _install(rows: list[dict]):
        seen: list[tuple[str, str | None]] = []

        class _Store:
            async def query_by_execution(
                self, execution_id: str, event_type: str | None = None, limit: int = 1000
            ) -> list[dict]:
                seen.append((execution_id, event_type))
                return [r for r in rows if r.get("execution_id") == execution_id]

        monkeypatch.setattr("syn_api._wiring.get_event_store_instance", lambda: _Store())
        return seen

    return _install


async def _capture_response(phases: list[dict]):
    """Seed one execution and return the model the HTTP endpoint hands back."""
    from syn_api.routes.executions.queries import get_execution_endpoint

    await _seed_execution_detail_with_phases("exec-capture", phases)
    return await get_execution_endpoint("exec-capture")


async def test_a_phase_carries_the_agent_sessions_its_capture_reported(_capture_rows):
    """(a) The join from an execution to its transcripts, in the reported order.

    Order is asserted, not just membership: the store returns the leader first
    and a client resuming a thread needs to know which one that was.
    """
    _capture_rows([_capture_row("host-uuid-1", agent_session_ids=["sess-codex", "sess-claude"])])

    response = await _capture_response([_phase("phase-1", "completed", session_id="host-uuid-1")])

    assert response.phases[0].agent_session_ids == ["sess-codex", "sess-claude"]


async def test_an_unreported_capture_is_null_not_an_empty_list(_capture_rows):
    """(b) A phase from a schema the field did not exist in reports NOTHING KNOWN.

    THE POINT OF THE ISSUE, with (c) below. `null` says "the exporter could not
    tell us"; `[]` would claim it swept and confirmed the phase produced no
    transcripts. A response model that defaults None to [] turns a version skew
    into a reported loss -- exactly the defect #1176 was filed for.
    """
    rows = [_capture_row("host-uuid-1", schema_version=1, agent_session_ids=["sess-codex"])]
    _capture_rows(rows)

    response = await _capture_response([_phase("phase-1", "completed", session_id="host-uuid-1")])

    assert response.phases[0].agent_session_ids is None
    # And null survives serialisation as null rather than vanishing or becoming [].
    assert response.phases[0].model_dump()["agent_session_ids"] is None


async def test_a_confirmed_empty_sweep_is_an_empty_list_not_null(_capture_rows):
    """(c) A schema 2 exporter that looked and found none said something.

    The counterpart to (b): this one MUST NOT read as null. An implementation
    that cannot tell these two apart has not fixed the issue.
    """
    rows = [_capture_row("host-uuid-1", schema_version=2, agent_session_ids=[])]
    _capture_rows(rows)

    response = await _capture_response([_phase("phase-1", "completed", session_id="host-uuid-1")])

    assert response.phases[0].agent_session_ids == []
    assert response.phases[0].agent_session_ids is not None


async def test_a_delegating_phase_reports_every_session_not_just_the_leader(_capture_rows):
    """(d) One phase, several agents: a codex leader, a claude delegate, a subagent.

    Truncating to the first is the plausible wrong implementation -- it looks
    right for every phase that did not delegate, which is most of them.
    """
    produced = ["sess-codex-leader", "sess-claude-delegate", "sess-claude-subagent"]
    rows = [_capture_row("host-uuid-1", agent_session_ids=produced)]
    _capture_rows(rows)

    response = await _capture_response([_phase("phase-1", "completed", session_id="host-uuid-1")])

    assert response.phases[0].agent_session_ids == produced


async def test_each_phase_gets_its_own_agent_sessions(_capture_rows):
    """The lookup is keyed per phase, so one execution's phases do not merge.

    A single execution-wide query serves every phase, which makes cross-talk
    between them the failure mode worth pinning: a leaked list would attribute
    one phase's transcripts to another, and auditing agent behaviour by phase is
    the whole point.
    """
    rows = [
        _capture_row("host-uuid-1", agent_session_ids=["sess-a"]),
        _capture_row("host-uuid-2", agent_session_ids=["sess-b", "sess-c"]),
        _capture_row("host-uuid-3", schema_version=2, agent_session_ids=[]),
    ]
    _capture_rows(rows)

    response = await _capture_response(
        [
            _phase("phase-1", "completed", session_id="host-uuid-1"),
            _phase("phase-2", "completed", session_id="host-uuid-2"),
            _phase("phase-3", "completed", session_id="host-uuid-3"),
            # No capture row at all, and no session id to find one by.
            _phase("phase-4", "pending"),
        ],
    )

    by_phase = {p.phase_id: p.agent_session_ids for p in response.phases}
    assert by_phase == {
        "phase-1": ["sess-a"],
        "phase-2": ["sess-b", "sess-c"],
        "phase-3": [],
        "phase-4": None,
    }


async def test_the_capture_lookup_runs_once_per_execution_not_once_per_phase(_capture_rows):
    """Four phases must not mean four round trips to the event store (#1077)."""
    rows = [_capture_row(f"host-uuid-{i}", agent_session_ids=[f"sess-{i}"]) for i in range(4)]
    seen = _capture_rows(rows)

    await _capture_response(
        [_phase(f"phase-{i}", "completed", session_id=f"host-uuid-{i}") for i in range(4)],
    )

    assert seen == [("exec-capture", "session_capture")], (
        f"expected one capture query for the whole execution, got {len(seen)}: {seen}"
    )


async def test_an_unreachable_event_store_reports_unknown_not_a_loss(
    monkeypatch: pytest.MonkeyPatch,
):
    """Telemetry being down cannot make a phase claim it produced no transcripts.

    Lane 2 failing must not fail the Lane 1 read, and must not answer `[]` --
    the honest answer to "we could not ask" is null.
    """

    class _BrokenStore:
        async def query_by_execution(
            self, execution_id: str, event_type: str | None = None, limit: int = 1000
        ) -> list[dict]:
            raise RuntimeError("AgentEventStore pool is not initialized")

    monkeypatch.setattr("syn_api._wiring.get_event_store_instance", lambda: _BrokenStore())

    response = await _capture_response([_phase("phase-1", "completed", session_id="host-uuid-1")])

    assert response.status == "running"
    assert response.phases[0].agent_session_ids is None
