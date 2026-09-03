"""An unmeasured phase duration must be stored as unknown, never as 0.0.

The projection seeded every phase's ``duration_seconds`` with ``0.0`` and
defaulted it to ``0.0`` again whenever a completion event carried no elapsed
time. Both are measurements -- and both read as "this phase finished
instantly". Downstream that is indistinguishable from a real sub-second phase,
so no read surface can recover from it: by the time the API sees the row the
information that nobody ever timed this phase is gone.

Storing ``None`` keeps the two apart, which is what lets the API boundary
compute a live duration for an in-flight phase and say "unknown" for a phase
that ended without one.
"""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def projection() -> WorkflowExecutionDetailProjection:
    return WorkflowExecutionDetailProjection(InMemoryProjectionStore())


async def _start_execution(proj: WorkflowExecutionDetailProjection) -> None:
    await proj.on_workflow_execution_started(
        {"execution_id": "exec-1", "workflow_id": "wf", "workflow_name": "wf"}
    )


async def _phase(proj: WorkflowExecutionDetailProjection) -> dict:
    row = await proj._store.get(proj.PROJECTION_NAME, "exec-1")
    return row["phases"][0]


class TestUnmeasuredDurationIsStoredAsUnknown:
    async def test_a_phase_that_has_only_started_has_no_duration(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        await _start_execution(projection)
        await projection.on_phase_started(
            {
                "execution_id": "exec-1",
                "phase_id": "p1",
                "phase_name": "p1",
                "started_at": "2026-09-01T12:00:00Z",
            }
        )
        assert (await _phase(projection))["duration_seconds"] is None

    async def test_a_completion_carrying_no_elapsed_time_leaves_it_unknown(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        # The event is the one the engine emits when it could not measure the
        # phase: tokens present, duration absent. Defaulting to 0.0 here
        # invented a measurement out of a missing field.
        await _start_execution(projection)
        await projection.on_phase_started(
            {
                "execution_id": "exec-1",
                "phase_id": "p1",
                "phase_name": "p1",
                "started_at": "2026-09-01T12:00:00Z",
            }
        )
        await projection.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "p1",
                "input_tokens": 10,
                "output_tokens": 3,
                "completed_at": "2026-09-01T12:00:20Z",
            }
        )
        assert (await _phase(projection))["duration_seconds"] is None

    async def test_a_measured_zero_still_survives(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        # The other half of the contract. A phase really can finish in under a
        # millisecond, and that 0.0 is evidence -- it must not be rewritten as
        # unknown just because unknown is now spelled with a different value.
        await _start_execution(projection)
        await projection.on_phase_started(
            {"execution_id": "exec-1", "phase_id": "p1", "phase_name": "p1"}
        )
        await projection.on_phase_completed(
            {"execution_id": "exec-1", "phase_id": "p1", "duration_seconds": 0.0}
        )
        assert (await _phase(projection))["duration_seconds"] == 0.0
