"""A salvaged phase is distinguishable where people actually look (#1300).

WHAT ROUND 2 FOUND. `PhaseCompletedEvent.deliverable_recovered` existed, was
correct, and reached nobody: the projection that turns that event into the
durable phase record had no field for it, so the stored record for a phase that
completed on a transcript recovery was identical to one that wrote its own
deliverable. A distinction only an event carries is invisible to every consumer
that matters.

WHY THE TEST WALKS THE WHOLE CHAIN. There are five hops between the event and
the HTTP response - projection, stored dict, `PhaseExecutionDetail`,
`PhaseExecution`, `PhaseExecutionInfo` - and each one re-lists its fields by
hand. This repository has dropped a field at exactly such a hop twice before
(#891, #1176). Asserting on either end would not have caught either. So the
value is put in as an event and read out of the model an API client receives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api.routes.executions.queries import _map_phase_detail, _map_phase_to_response
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import PhaseExecutionInfo

EXECUTION_ID = "exec-1300-readmodel"
PHASE_ID = "phase-implement"
SESSION_ID = "sess-1300"


class _NoProjections:
    """A manager with nothing on it.

    Both enrichment lookups in `_map_phase_detail` are guarded and fall back to
    their defaults, which is what this test wants: the subject is one field
    travelling, not Lane 2 cost merging.
    """


async def _phase_as_an_api_client_sees_it(
    *, recovered: bool, phase_started: bool = True
) -> PhaseExecutionInfo:
    """Drive a phase from PhaseCompleted all the way to the response model.

    `phase_started=False` selects the projection's OTHER branch: a completion
    whose PhaseStarted never arrived builds the record from scratch instead of
    updating one, and that branch re-lists its fields somewhere else entirely.
    """
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)

    await projection.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1300",
            "workflow_name": "sdlc-implement",
            "started_at": "2026-09-17T10:00:00+00:00",
            "total_phases": 1,
        }
    )
    if phase_started:
        await projection.on_phase_started(
            {
                "execution_id": EXECUTION_ID,
                "phase_id": PHASE_ID,
                "phase_name": "implement",
                "session_id": SESSION_ID,
                "started_at": "2026-09-17T10:00:05+00:00",
            }
        )
    await projection.on_phase_completed(
        {
            "execution_id": EXECUTION_ID,
            "phase_id": PHASE_ID,
            "session_id": SESSION_ID,
            "artifact_id": "art-1300",
            "completed_at": "2026-09-17T10:09:30+00:00",
            "duration_seconds": 565.0,
            "input_tokens": 120_000,
            "output_tokens": 9_000,
            "total_tokens": 129_000,
            "deliverable_recovered": recovered,
        }
    )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EXECUTION_ID)
    assert record is not None, "the projection must have stored the execution"
    detail = WorkflowExecutionDetail.from_dict(record)
    mapped = await _map_phase_detail(
        detail.phases[0],
        _NoProjections(),  # pyright: ignore[reportArgumentType]
        {},
    )
    return _map_phase_to_response(mapped)


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_salvaged_phase_says_so_all_the_way_to_the_response() -> None:
    """The flag survives every hop between the event and the API client.

    True is a value that cannot arise by accident here: the field defaults to
    False at all five hops, so the only way it arrives True is by being carried.
    """
    phase = await _phase_as_an_api_client_sees_it(recovered=True)

    assert phase.status == "completed", "a salvaged phase completes - that is the whole fix"
    assert phase.deliverable_recovered is True


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_phase_that_wrote_its_own_deliverable_is_told_apart() -> None:
    """The distinction is a distinction, not a field that is always set.

    Paired with the test above deliberately: `status` reads "completed" for
    both, so if this one also reported True there would be nothing to read.
    """
    phase = await _phase_as_an_api_client_sees_it(recovered=False)

    assert phase.status == "completed"
    assert phase.deliverable_recovered is False


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_completion_with_no_start_event_records_the_salvage_too() -> None:
    """The projection's other branch carries the flag as well.

    `on_phase_completed` builds a record from scratch when PhaseStarted never
    landed - a replay from a truncated stream, a projection rebuilt after the
    start event aged out. A fix that covered only the update branch would
    report a clean phase for exactly the runs whose history is already thin.
    """
    phase = await _phase_as_an_api_client_sees_it(recovered=True, phase_started=False)

    assert phase.deliverable_recovered is True
