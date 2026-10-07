"""At-least-once delivery: a redelivered event, or one retried after a partial
write, leaves the scorecard's records exactly as one delivery would (#1727)."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.slices.scorecard import ScorecardProjection
from syn_domain.contexts.orchestration.slices.scorecard.projection import (
    OPEN_RUNS_KEY,
    SCORECARD_DAYS,
    SCORECARD_RUNS,
)
from syn_domain.contexts.orchestration.slices.scorecard.test_scorecard import (
    _at,
    _deliver,
    _failed,
    _started,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

pytestmark = pytest.mark.unit

DAY = "2026-10-07"


class _FailingStore(InMemoryProjectionStore):
    """Raises on the ``after + 1``-th save to ``projection``/``key`` once armed."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_on: tuple[str, str] | None = None
        self.after = 0

    async def save(self, projection: str, key: str, data: object) -> None:  # type: ignore[override]
        if self.fail_on == (projection, key):
            if self.after:
                self.after -= 1
            else:
                self.fail_on = None
                raise RuntimeError(f"injected write failure on {projection}/{key}")
        await super().save(projection, key, data)  # type: ignore[arg-type]


async def _attempt(projection: ScorecardProjection, event: DomainEvent) -> None:
    """One delivery that may fail part-way; the dispatcher then redelivers it."""
    envelope = EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="execution",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            event_type=event.event_type,
            global_nonce=1,
        ),
    )
    with contextlib.suppress(RuntimeError):
        await projection.handle_event(envelope, MemoryCheckpointStore())


def _phase(phase_id: str, tokens: int) -> PhaseCompletedEvent:
    return PhaseCompletedEvent(
        workflow_id="wf",
        execution_id="e1",
        phase_id=phase_id,
        completed_at=_at(1),
        success=True,
        session_id=f"s-{phase_id}",
        total_tokens=tokens,
    )


async def test_a_redelivered_phase_is_recorded_once_with_its_own_tokens() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _deliver(projection, _started("e1", start=0))
    phases = [_phase("implement", 100), _phase("verify", 900)]
    for event in phases:
        await _deliver(projection, event)
    # The checkpoint save failed after the SECOND phase was persisted: redelivered.
    await _deliver(projection, phases[1])

    run = await projection.get_run("e1")
    assert run is not None
    for event in phases:
        recorded = [p for p in run.phases if p.phase_id == event.phase_id]
        assert len(recorded) == 1, event.phase_id
        assert recorded[0].total_tokens == event.total_tokens, event.phase_id


async def test_a_failure_retried_after_its_phase_was_saved_records_the_phase_once() -> None:
    store = _FailingStore()
    projection = ScorecardProjection(store)
    await _deliver(projection, _started("e1", start=0))
    failure = _failed(
        "e1",
        end=2,
        classification=FailureClassification.PLATFORM,
        phase_id="verify",
        input_tokens=700,
    )
    # The failed phase is saved (first write to the run), then the terminal
    # update of the same run (its second write) fails.
    store.fail_on = (SCORECARD_RUNS, "e1")
    store.after = 1
    await _attempt(projection, failure)
    await _deliver(projection, failure)

    run = await projection.get_run("e1")
    assert run is not None
    assert [(p.phase_id, p.total_tokens) for p in run.phases] == [("verify", 700)]


@pytest.mark.parametrize("failing_key", [DAY, OPEN_RUNS_KEY])
async def test_a_terminal_write_retried_after_a_partial_index_update_is_found_once(
    failing_key: str,
) -> None:
    store = _FailingStore()
    projection = ScorecardProjection(store)
    await _deliver(projection, _started("e1", start=0))
    failure = _failed("e1", end=2, classification=FailureClassification.TASK)
    store.fail_on = (SCORECARD_DAYS, failing_key)
    await _attempt(projection, failure)
    await _deliver(projection, failure)

    found = await projection.runs_for_days([DAY])
    assert [r.execution_id for r in found] == ["e1"]
    assert "e1" in (await projection._index(DAY)).execution_ids
    assert "e1" not in (await projection._index(OPEN_RUNS_KEY)).execution_ids


async def test_a_failed_phase_keeps_the_session_its_agent_ran_in() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _deliver(projection, _started("e1", start=0))
    await _deliver(
        projection,
        WorkspaceProvisionedForPhaseEvent(
            workflow_id="wf",
            execution_id="e1",
            phase_id="verify",
            workspace_id="w1",
            session_id="s-verify",
            provisioned_at=_at(0.5),
        ),
    )
    await _deliver(
        projection,
        AgentExecutionCompletedEvent(
            workflow_id="wf",
            execution_id="e1",
            phase_id="verify",
            session_id="s-verify",
            completed_at=_at(1),
            exit_code=1,
        ),
    )
    await _deliver(
        projection,
        _failed(
            "e1",
            end=2,
            classification=FailureClassification.TASK,
            phase_id="verify",
            input_tokens=500,
        ),
    )

    run = await projection.get_run("e1")
    assert run is not None
    assert [(p.phase_id, p.session_id) for p in run.phases] == [("verify", "s-verify")]


async def test_a_failed_phase_with_no_session_observation_has_none() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _deliver(projection, _started("e1", start=0))
    await _deliver(
        projection,
        _failed("e1", end=2, classification=FailureClassification.PLATFORM, phase_id="verify"),
    )

    run = await projection.get_run("e1")
    assert run is not None
    assert [(p.phase_id, p.session_id) for p in run.phases] == [("verify", None)]
