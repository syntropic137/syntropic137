"""A read surface must never answer "how long has this run" with a bare 0.0.

Every test here drives a real production read path - the route function or the
projection query it calls - and asserts on the number a client would receive.
Each one failed before this change, all with the same symptom: a duration of
0.0 reported for something that was simultaneously reported as ``running``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

# Long enough that no plausible test-runner delay could produce it, and far
# enough from 0.0 that a regression cannot hide inside a tolerance.
ELAPSED = 300.0


def _started_seconds_ago(seconds: float) -> str:
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


# =============================================================================
# GET /metrics?workflow_id=... - per-phase breakdown
# =============================================================================


async def _phase_metrics(workflow_id: str):
    """Call the real endpoint helper that builds the /metrics phase rows."""
    from syn_api.routes.metrics import _build_phase_metrics

    return {p.phase_id: p for p in await _build_phase_metrics(workflow_id)}


async def _phase_projection():
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    return get_projection_mgr().workflow_phase_metrics


class TestMetricsEndpointPhaseDuration:
    @pytest.mark.asyncio
    async def test_running_phase_reports_elapsed_time_not_zero(self) -> None:
        """The defect verbatim: status "running" beside duration 0.0."""
        projection = await _phase_projection()
        await projection.on_phase_started(
            {
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "phase_name": "Build",
                "started_at": _started_seconds_ago(ELAPSED),
            }
        )

        phase = (await _phase_metrics("wf-1"))["p-1"]

        assert phase.status == "running"
        assert phase.duration_seconds is not None
        assert phase.duration_seconds >= ELAPSED

    @pytest.mark.asyncio
    async def test_running_phase_duration_advances_between_reads(self) -> None:
        """Not merely non-zero: it has to track the clock.

        A duration frozen at whatever it was when the phase started is
        indistinguishable from a hang, which is how six healthy runs got
        cancelled. Two reads of a live phase must differ.
        """
        projection = await _phase_projection()
        await projection.on_phase_started(
            {
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "phase_name": "Build",
                "started_at": _started_seconds_ago(ELAPSED),
            }
        )

        first = (await _phase_metrics("wf-1"))["p-1"].duration_seconds
        await asyncio.sleep(0.05)
        second = (await _phase_metrics("wf-1"))["p-1"].duration_seconds

        assert first is not None
        assert second is not None
        assert second > first

    @pytest.mark.asyncio
    async def test_rerun_phase_adds_to_the_settled_total(self) -> None:
        """This projection is keyed by workflow, so a phase's runs accumulate.

        Reporting only the live run would make the workflow's total go
        BACKWARDS the moment a phase is retried - the same erasure #1036 fixed
        on the write side.
        """
        projection = await _phase_projection()
        await projection.on_phase_completed(
            {
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "phase_name": "Build",
                "duration_seconds": 10.0,
                "success": True,
            }
        )
        await projection.on_phase_started(
            {
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "phase_name": "Build",
                "started_at": _started_seconds_ago(ELAPSED),
            }
        )

        phase = (await _phase_metrics("wf-1"))["p-1"]

        assert phase.status == "running"
        assert phase.duration_seconds is not None
        assert phase.duration_seconds >= ELAPSED + 10.0

    @pytest.mark.asyncio
    async def test_finished_phase_that_recorded_no_duration_is_unknown(self) -> None:
        """Unknown is None. 0.0 would claim the phase finished instantly."""
        projection = await _phase_projection()
        await projection.on_phase_completed(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build", "success": True}
        )

        phase = (await _phase_metrics("wf-1"))["p-1"]

        assert phase.status == "completed"
        assert phase.duration_seconds is None

    @pytest.mark.asyncio
    async def test_running_phase_with_unusable_start_is_unknown(self) -> None:
        """A start we cannot parse is unknown, not zero, and never raises."""
        projection = await _phase_projection()
        await projection.on_phase_started(
            {
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "phase_name": "Build",
                "started_at": "not-a-timestamp",
            }
        )

        phase = (await _phase_metrics("wf-1"))["p-1"]

        assert phase.status == "running"
        assert phase.duration_seconds is None


# =============================================================================
# Execution timelines: GET /repos/{id}/activity, /systems/{id}/activity,
# /systems/{id}/history - three routes over one shared read model
# =============================================================================


async def _seed_execution(status: str, started_at: str, completed_at: str | None) -> None:
    """Seed one execution, correlated to a repo that belongs to a system."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_api._wiring import ensure_connected

    await ensure_connected()
    store = get_projection_store()
    await store.save(
        "systems",
        "sys-1",
        {"system_id": "sys-1", "organization_id": "org", "name": "Platform"},
    )
    await store.save(
        "repos",
        "org/repo",
        {
            "repo_id": "org/repo",
            "organization_id": "org",
            "system_id": "sys-1",
            "provider": "github",
            "provider_repo_id": "1",
            "full_name": "org/repo",
            "owner": "org",
            "default_branch": "main",
            "installation_id": "",
            "is_private": False,
            "created_by": "",
            "created_at": None,
            "is_deregistered": False,
        },
    )
    await store.save(
        "repo_correlation",
        "c1",
        {"execution_id": "exec-1", "repo_full_name": "org/repo"},
    )
    await store.save(
        "workflow_executions",
        "exec-1",
        {
            "workflow_execution_id": "exec-1",
            "workflow_id": "wf-1",
            "workflow_name": "Deploy",
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
        },
    )


async def _timeline_entries():
    """The single entry each of the three timeline routes returns for it."""
    from syn_api.routes.repos import get_repo_activity_endpoint
    from syn_api.routes.systems import (
        get_system_activity_endpoint,
        get_system_history_endpoint,
    )

    return {
        "repo_activity": (await get_repo_activity_endpoint("org/repo")).entries[0],
        "system_activity": (await get_system_activity_endpoint("sys-1")).entries[0],
        "system_history": (await get_system_history_endpoint("sys-1")).entries[0],
    }


class TestExecutionTimelineDuration:
    @pytest.mark.asyncio
    async def test_running_execution_is_not_reported_as_instant(self) -> None:
        """All three timelines answered 0.0 for an execution still running.

        They now answer what every other read surface answers: the time
        elapsed since it started, resolved at read time.
        """
        await _seed_execution("running", _started_seconds_ago(ELAPSED), None)

        for surface, entry in (await _timeline_entries()).items():
            assert entry.status == "running", surface
            assert entry.duration_seconds is not None, surface
            assert entry.duration_seconds >= ELAPSED, surface
            assert entry.completed_at is None, surface

    @pytest.mark.asyncio
    async def test_running_execution_does_not_break_the_timeline(self) -> None:
        """The absent completion must stay absent all the way to the client.

        These routes rendered it with ``str()``, producing the string "None",
        which is not a timestamp and not empty either: the response model
        rejected it and the whole timeline 500'd whenever any one execution on
        it was still running.
        """
        from syn_api.routes.repos import get_repo_activity_endpoint

        await _seed_execution("running", _started_seconds_ago(ELAPSED), None)

        response = await get_repo_activity_endpoint("org/repo")

        assert response.total == 1
        assert response.entries[0].execution_id == "exec-1"

    @pytest.mark.asyncio
    async def test_completed_execution_keeps_its_measured_duration(self) -> None:
        """The fix must not cost the case that already worked."""
        await _seed_execution("completed", "2026-03-06T10:00:00+00:00", "2026-03-06T10:05:00+00:00")

        for surface, entry in (await _timeline_entries()).items():
            assert entry.duration_seconds == ELAPSED, surface
