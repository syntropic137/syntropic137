"""Every read surface must report the SAME duration for the same run.

These are consumer tests, deliberately. ``resolve_duration_seconds`` has its
own unit tests in ``packages/syn-shared/tests/test_display_formatters.py``; what
those cannot catch is the failure mode this codebase actually produces -- a
value computed correctly and then dropped, defaulted or re-frozen one hop
later, by a response model with ``= 0.0`` on it or by a projection that never
stopped seeding zeros. So each test here drives the real endpoint or service
function and asserts on what a client would receive.

The fixture durations are chosen so they could not arise any other way: a phase
seeded as started ~600s ago against a stored ``duration_seconds`` of 0.0 or
1.5. A surface reporting the stored number, or ``None``, or ``0.0``, fails.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from syn_api.types import Ok

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

#: How long ago the fixtures claim work started. Large enough that no rounding,
#: no stored 0.0 and no 1.5s stale value can be mistaken for it.
RAN_FOR_SECONDS = 600.0

#: A stale duration the projection recorded before the phase finished. Any
#: surface that prefers this over the wall clock for in-flight work is the
#: frozen-duration regression.
STALE_RECORDED_SECONDS = 1.5


def _iso_seconds_ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


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


async def _seed_running_execution(exec_id: str, started_at: str) -> None:
    """Seed one running execution into BOTH projections, mid-flight.

    Shaped exactly as the projections leave it: phase 1 completed with a real
    recorded duration, phase 2 still running with a stale recorded value and no
    ``completed_at``, phase 3 never started. The execution's stored
    ``total_duration_seconds`` covers only the phase that ENDED.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()

    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        exec_id,
        {
            "workflow_execution_id": exec_id,
            "workflow_id": "wf-1",
            "workflow_name": "Workflow A",
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
            "completed_phases": 1,
            "total_phases": 3,
            "total_tokens": 10,
            "total_cost_usd": "0",
            "tool_call_count": 1,
            "error_message": None,
        },
    )
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "execution_id": exec_id,
            "workflow_execution_id": exec_id,
            "workflow_id": "wf-1",
            "workflow_name": "Workflow A",
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "total_duration_seconds": 12.0,
            "artifact_ids": [],
            "error_message": None,
            "phases": [
                {
                    "phase_id": "phase-done",
                    "name": "Done",
                    "status": "completed",
                    "session_id": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "duration_seconds": 12.0,
                    "started_at": started_at,
                    "completed_at": _iso_seconds_ago(RAN_FOR_SECONDS - 12.0),
                    "error_message": None,
                },
                {
                    "phase_id": "phase-running",
                    "name": "Running",
                    "status": "running",
                    "session_id": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "duration_seconds": STALE_RECORDED_SECONDS,
                    "started_at": started_at,
                    "completed_at": None,
                    "error_message": None,
                },
                {
                    "phase_id": "phase-pending",
                    "name": "Pending",
                    "status": "pending",
                    "session_id": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "duration_seconds": 0.0,
                    "started_at": started_at,
                    "completed_at": None,
                    "error_message": None,
                },
            ],
        },
    )


# -- Executions ---------------------------------------------------------------


async def test_execution_list_reports_a_live_duration_for_a_running_run() -> None:
    """The LIST endpoint, not just the detail.

    It previously required both timestamps, so anything still running reported
    nothing at all while the detail page beside it reported a live figure --
    the two surfaces disagreeing about the same run at the same instant.
    """
    from syn_api.routes.executions.queries import list_executions_endpoint

    await _seed_running_execution("exec-live", _iso_seconds_ago(RAN_FOR_SECONDS))

    response = await list_executions_endpoint(status=None, page=1, page_size=50)
    (summary,) = response.executions

    assert summary.duration_seconds is not None, "the list dropped the running duration"
    assert summary.duration_seconds == pytest.approx(RAN_FOR_SECONDS, abs=30.0)
    assert summary.duration_display not in ("", "—", "<1s")


async def test_execution_list_and_detail_agree_about_the_same_run() -> None:
    """The premise of the whole change: one run, one number."""
    from syn_api.routes.executions.queries import (
        get_execution_endpoint,
        list_executions_endpoint,
    )

    await _seed_running_execution("exec-agree", _iso_seconds_ago(RAN_FOR_SECONDS))

    listed = (await list_executions_endpoint(status=None, page=1, page_size=50)).executions[0]
    detail = await get_execution_endpoint("exec-agree")

    assert listed.duration_seconds is not None
    assert detail.total_duration_seconds is not None
    assert detail.total_duration_seconds == pytest.approx(listed.duration_seconds, abs=30.0)


async def test_execution_total_includes_the_phase_still_running() -> None:
    """The stored total only grows when a phase ENDS.

    So a run whose current phase is in flight reported a flat 12s next to a
    phase visibly counting past 600s. The total must cover the live phase.
    """
    from syn_api.routes.executions import get_detail

    await _seed_running_execution("exec-total", _iso_seconds_ago(RAN_FOR_SECONDS))

    result = await get_detail("exec-total")
    assert isinstance(result, Ok)
    total = result.value.total_duration_seconds

    assert total is not None
    assert total > 12.0, f"total {total} is the stored value; the live phase was excluded"
    assert total == pytest.approx(12.0 + RAN_FOR_SECONDS, abs=30.0)


async def test_execution_total_advances_while_a_phase_is_running() -> None:
    """Frozen-total canary. A memoized or stored total cannot move."""
    from syn_api.routes.executions import get_detail

    await _seed_running_execution("exec-advance", _iso_seconds_ago(RAN_FOR_SECONDS))

    first = await get_detail("exec-advance")
    await asyncio.sleep(0.05)
    second = await get_detail("exec-advance")

    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert first.value.total_duration_seconds is not None
    assert second.value.total_duration_seconds is not None
    assert second.value.total_duration_seconds > first.value.total_duration_seconds, (
        "the execution total did not advance across a running phase; it is frozen"
    )


async def test_running_phase_ignores_the_stale_recorded_duration() -> None:
    """A running phase has a stale ``duration_seconds`` in the projection.

    Reading it back is the 2026-09-01 incident: the number stopped moving and
    six healthy runs were cancelled as hung. 600s of elapsed time cannot be
    produced by returning the stored 1.5.
    """
    from syn_api.routes.executions import get_detail

    await _seed_running_execution("exec-stale", _iso_seconds_ago(RAN_FOR_SECONDS))

    result = await get_detail("exec-stale")
    assert isinstance(result, Ok)
    running = next(p for p in result.value.phases if p.phase_id == "phase-running")

    assert running.duration_seconds is not None
    assert running.duration_seconds != pytest.approx(STALE_RECORDED_SECONDS)
    assert running.duration_seconds == pytest.approx(RAN_FOR_SECONDS, abs=30.0)


async def test_pending_phase_reports_unknown_not_zero() -> None:
    """A pending phase carries the execution's ``started_at``, so a span IS
    computable -- it just is not this phase's duration. It has not run.

    ``0.0`` renders as "completed instantly", which is a measurement nobody
    made (#1076 review finding 3).
    """
    from syn_api.routes.executions.queries import get_execution_endpoint

    await _seed_running_execution("exec-pending", _iso_seconds_ago(RAN_FOR_SECONDS))

    detail = await get_execution_endpoint("exec-pending")
    pending = next(p for p in detail.phases if p.phase_id == "phase-pending")

    assert pending.duration_seconds is None, (
        f"pending phase reported {pending.duration_seconds}; only None is honest"
    )


async def test_completed_phase_keeps_the_duration_measured_at_the_source() -> None:
    """The live path must not swallow real measurements."""
    from syn_api.routes.executions import get_detail

    await _seed_running_execution("exec-done-phase", _iso_seconds_ago(RAN_FOR_SECONDS))

    result = await get_detail("exec-done-phase")
    assert isinstance(result, Ok)
    done = next(p for p in result.value.phases if p.phase_id == "phase-done")

    assert done.duration_seconds == pytest.approx(12.0)


async def test_execution_with_nothing_measured_reports_unknown_not_zero() -> None:
    """An execution nobody has measured is not one that took no time."""
    from syn_api._wiring import ensure_connected, get_projection_mgr
    from syn_api.routes.executions import get_detail

    await ensure_connected()
    manager = get_projection_mgr()
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        "exec-unmeasured",
        {
            "execution_id": "exec-unmeasured",
            "workflow_execution_id": "exec-unmeasured",
            "workflow_id": "wf-1",
            "workflow_name": "Workflow A",
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "artifact_ids": [],
            "error_message": None,
            "phases": [],
        },
    )

    result = await get_detail("exec-unmeasured")
    assert isinstance(result, Ok)
    assert result.value.total_duration_seconds is None


# -- Sessions -----------------------------------------------------------------


async def _seed_running_session(session_id: str, started_at: str) -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()
    await manager.session_list._store.save(
        "session_summaries",
        session_id,
        {
            "id": session_id,
            "session_id": session_id,
            "workflow_id": "wf-1",
            "execution_id": "exec-1",
            "phase_id": "phase-running",
            "status": "running",
            "agent_type": "claude",
            "repos": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": "0",
            "started_at": started_at,
            "completed_at": None,
            "duration_seconds": None,
        },
    )


async def test_session_list_reports_a_live_duration_for_a_running_session() -> None:
    """Lane 2 only records ``duration_ms`` once a session ENDS, so a running
    session reported nothing at every list read.
    """
    from syn_api.routes.sessions import list_sessions_endpoint

    await _seed_running_session("sess-live", _iso_seconds_ago(RAN_FOR_SECONDS))

    response = await list_sessions_endpoint(
        workflow_id=None,
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        limit=50,
    )
    (summary,) = response.sessions

    assert summary.duration_seconds is not None
    assert summary.duration_seconds == pytest.approx(RAN_FOR_SECONDS, abs=30.0)


async def test_session_list_and_detail_agree_about_the_same_session() -> None:
    from syn_api.routes.sessions import get_session_endpoint, list_sessions_endpoint

    await _seed_running_session("sess-agree", _iso_seconds_ago(RAN_FOR_SECONDS))

    listed = (
        await list_sessions_endpoint(
            workflow_id=None,
            status=None,
            statuses=None,
            started_after=None,
            started_before=None,
            limit=50,
        )
    ).sessions[0]
    detail = await get_session_endpoint("sess-agree")

    assert listed.duration_seconds is not None
    assert detail.duration_seconds is not None
    assert detail.duration_seconds == pytest.approx(listed.duration_seconds, abs=30.0)


# -- Repo / system activity ---------------------------------------------------


async def test_repo_activity_reports_a_live_duration_for_a_running_execution() -> None:
    """Three org-context handlers each had their own ``_compute_duration`` that
    returned ``0.0`` for anything without a ``completed_at``. The response
    model then had ``duration_seconds: float = 0.0`` on it, which is the hop
    that would have dropped the fix even once the handler was right.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr
    from syn_api.types import RepoActivityEntryResponse
    from syn_domain.contexts.organization.slices.repo_activity.GetRepoActivityHandler import (
        GetRepoActivityHandler,
        GetRepoActivityQuery,
    )

    await ensure_connected()
    manager = get_projection_mgr()
    store = manager.store
    started_at = _iso_seconds_ago(RAN_FOR_SECONDS)

    await store.save(
        "repo_correlation",
        "exec-live:acme/api",
        {"repo_full_name": "acme/api", "execution_id": "exec-live"},
    )
    await store.save(
        "workflow_executions",
        "exec-live",
        {
            "workflow_execution_id": "exec-live",
            "workflow_id": "wf-1",
            "workflow_name": "Workflow A",
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
        },
    )

    # A second execution that is queued and has never run: no timestamps, so
    # nothing can measure it and the honest answer is unknown. This is the case
    # the response model used to destroy, and the one a running-execution-only
    # test cannot see.
    await store.save(
        "repo_correlation",
        "exec-unmeasurable:acme/api",
        {"repo_full_name": "acme/api", "execution_id": "exec-unmeasurable"},
    )
    await store.save(
        "workflow_executions",
        "exec-unmeasurable",
        {
            "workflow_execution_id": "exec-unmeasurable",
            "workflow_id": "wf-1",
            "workflow_name": "Workflow A",
            "status": "pending",
            "started_at": None,
            "completed_at": None,
        },
    )

    handler = GetRepoActivityHandler(store)
    entries = await handler.handle(GetRepoActivityQuery(repo_id="acme/api"))
    by_id = {e.execution_id: e for e in entries}

    assert set(by_id) == {"exec-live", "exec-unmeasurable"}
    live = by_id["exec-live"]
    assert live.duration_seconds is not None
    assert live.duration_seconds == pytest.approx(RAN_FOR_SECONDS, abs=30.0)
    assert by_id["exec-unmeasurable"].duration_seconds is None

    # The response model is the hop that drops it. ``duration_seconds: float =
    # 0.0`` rejects the unknown outright (ValidationError) or coerces it into a
    # measurement nobody made; ``started_at``/``completed_at`` declared as
    # datetimes did the same to a running execution's empty completed_at,
    # 500ing the whole timeline.
    responses = {e.execution_id: RepoActivityEntryResponse(**e.to_dict()) for e in entries}
    assert responses["exec-live"].duration_seconds == pytest.approx(live.duration_seconds)
    assert responses["exec-live"].completed_at is None
    assert responses["exec-unmeasurable"].duration_seconds is None
