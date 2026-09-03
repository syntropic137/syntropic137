"""A cancelled or interrupted phase must report how long it actually ran.

Same defect as #1036 (a failed phase reporting 0.0), in the two handlers that
change never reached. `PhaseDetail.running()` seeds `duration_seconds` at 0.0,
and cancellation set only `phase["status"]`, so a phase cancelled after 400
seconds reported 0.0 - a value indistinguishable from a real measurement of an
instantaneous phase.

Not hypothetical: six runs were cancelled mid-flight on 2026-09-01 and every one
of them reports 0.0 today.

WHY THE DURATION IS COMPUTED HERE rather than read off the event: the failed
path receives `failed_phase_duration_seconds` from the processor, but cancel and
interrupt events carry only a timestamp. The elapsed time is therefore derived
from the phase's own `started_at` against that timestamp - NOT against the wall
clock, which would keep growing forever after the run ended.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

STARTED = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
RAN_FOR_SECONDS = 400.0
ENDED = STARTED + timedelta(seconds=RAN_FOR_SECONDS)


async def _projection_with_running_phase() -> WorkflowExecutionDetailProjection:
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await detail.on_workflow_execution_started(
        {"execution_id": "exec-1", "workflow_id": "wf-1", "workflow_name": "Test Workflow"}
    )
    await detail.on_phase_started(
        {
            "execution_id": "exec-1",
            "phase_id": "p-1",
            "phase_name": "Phase 1",
            "started_at": STARTED.isoformat(),
        }
    )
    row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
    assert row is not None
    phase = next(p for p in row["phases"] if p["phase_id"] == "p-1")
    # The precondition the whole test rests on: a running phase is seeded 0.0.
    assert not phase.get("duration_seconds")
    return detail


async def _phase_after(detail: WorkflowExecutionDetailProjection) -> dict:
    row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
    assert row is not None
    return next(p for p in row["phases"] if p["phase_id"] == "p-1")


class TestCancelledPhaseReportsItsRealDuration:
    async def test_cancelled_phase_is_not_reported_as_instantaneous(self) -> None:
        detail = await _projection_with_running_phase()

        await detail.on_execution_cancelled(
            {
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "cancelled_at": ENDED.isoformat(),
                "reason": "Cancelled by user",
            }
        )

        phase = await _phase_after(detail)
        assert phase["status"] == "cancelled"
        assert phase["duration_seconds"] == pytest.approx(RAN_FOR_SECONDS, abs=1.0)

    async def test_cancelled_phase_records_when_it_ended(self) -> None:
        """Without completed_at the duration cannot be recomputed or audited."""
        detail = await _projection_with_running_phase()

        await detail.on_execution_cancelled(
            {"execution_id": "exec-1", "phase_id": "p-1", "cancelled_at": ENDED.isoformat()}
        )

        assert (await _phase_after(detail))["completed_at"] == ENDED.isoformat()

    async def test_interrupted_phase_gets_the_same_treatment(self) -> None:
        """Interruption is the same defect in the sibling handler. Fixing one
        and not the other would leave half the class open."""
        detail = await _projection_with_running_phase()

        await detail.on_workflow_interrupted(
            {
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "interrupted_at": ENDED.isoformat(),
                "reason": "Interrupted by user",
            }
        )

        phase = await _phase_after(detail)
        assert phase["status"] == "interrupted"
        assert phase["duration_seconds"] == pytest.approx(RAN_FOR_SECONDS, abs=1.0)

    async def test_the_duration_is_frozen_at_cancellation_not_still_running(self) -> None:
        """The value must be measured against the cancellation timestamp.

        Measured against the wall clock it would keep growing after the run
        ended, so a long-finished cancelled phase would report a duration that
        rises every time the page is refreshed. The fixture's timestamps are in
        the past, so a wall-clock implementation returns something vastly larger
        than 400s and this fails.
        """
        detail = await _projection_with_running_phase()

        await detail.on_execution_cancelled(
            {"execution_id": "exec-1", "phase_id": "p-1", "cancelled_at": ENDED.isoformat()}
        )

        assert (await _phase_after(detail))["duration_seconds"] < RAN_FOR_SECONDS * 2

    async def test_a_cancelled_phase_rolls_into_the_execution_total(self) -> None:
        """Otherwise the execution under-reports by exactly the cancelled
        phase's time, which is the same accounting gap #1036 closed for
        failures."""
        detail = await _projection_with_running_phase()

        await detail.on_execution_cancelled(
            {"execution_id": "exec-1", "phase_id": "p-1", "cancelled_at": ENDED.isoformat()}
        )

        row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
        assert row is not None
        assert row.get("total_duration_seconds") == pytest.approx(RAN_FOR_SECONDS, abs=1.0)

    async def test_an_already_completed_phase_is_not_touched_at_all(self) -> None:
        """Cancelling an execution must not rewrite a phase that already finished.

        Asserts STATUS and completed_at too, not just duration. The first
        version of this test checked duration alone and passed against an
        implementation that still relabelled a completed phase `cancelled` -
        a review found the gap, which is the test being wrong rather than the
        code.
        """
        detail = await _projection_with_running_phase()
        finished_at = (STARTED + timedelta(seconds=12.5)).isoformat()
        await detail.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "duration_seconds": 12.5,
                "completed_at": finished_at,
            }
        )

        await detail.on_execution_cancelled(
            {"execution_id": "exec-1", "phase_id": "p-1", "cancelled_at": ENDED.isoformat()}
        )

        phase = await _phase_after(detail)
        assert phase["duration_seconds"] == pytest.approx(12.5, abs=0.1)
        assert phase["status"] == "completed"
        assert phase["completed_at"] == finished_at

    async def test_a_completed_phase_measured_at_zero_is_still_a_measurement(self) -> None:
        """The case a truthiness guard gets wrong.

        `if not phase["duration_seconds"]` treats a real measurement of 0.0 as
        "no duration recorded", so cancelling would recompute this phase as 400
        seconds and add 400 seconds to the execution total. Zero is a value.
        """
        detail = await _projection_with_running_phase()
        await detail.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "duration_seconds": 0.0,
                "completed_at": STARTED.isoformat(),
            }
        )

        await detail.on_execution_cancelled(
            {"execution_id": "exec-1", "phase_id": "p-1", "cancelled_at": ENDED.isoformat()}
        )

        phase = await _phase_after(detail)
        assert phase["duration_seconds"] == 0.0
        assert phase["status"] == "completed"
        row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
        assert row is not None
        assert not row.get("total_duration_seconds")

    async def test_a_repeated_cancellation_does_not_double_count(self) -> None:
        """Projections are replayed. The second application must be a no-op."""
        detail = await _projection_with_running_phase()
        event = {"execution_id": "exec-1", "phase_id": "p-1", "cancelled_at": ENDED.isoformat()}

        await detail.on_execution_cancelled(event)
        await detail.on_execution_cancelled(event)

        row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
        assert row is not None
        assert row.get("total_duration_seconds") == pytest.approx(RAN_FOR_SECONDS, abs=1.0)
