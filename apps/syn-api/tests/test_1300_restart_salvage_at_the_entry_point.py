"""A restart between an agent finishing and its artifacts being collected (#1300).

WHY THIS TEST IS HERE AND NOT IN syn-domain. The salvage was already hardened,
already event-sourced and already covered by a restart test - and it still did
nothing in production, because production does not resume a stranded execution
through `WorkflowExecutionProcessor`. It reaches it through exactly one door:
`lifecycle._init_degradable_services` calls `reconcile_orphaned_executions`,
which used to fail every execution still RUNNING without looking at what it was
throwing away. A test that drives the processor cannot see that; this one enters
where production enters.

WHAT IT RULES OUT. The aggregate handed to reconciliation is rebuilt from stored
event envelopes and has never been touched by the code that recorded them, so
nothing carried over in memory. The artifact is read back out of the repository
the collector actually stored it through, and `PhaseCompleted` out of the event
stream - not off a return value - because the two ends of this change agreeing
is the failure mode the value has to survive, not evidence that it did.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
    ProvisionWorkspaceCompletedCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

from syn_api.services.reconciliation import CleanupResult, reconcile_orphaned_executions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent, EventEnvelope

_REAPED = CleanupResult(fully_reaped=True)
_CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)
EXECUTION_ID = "exec-1300-reconcile"
WORKFLOW_ID = "wf-1300-reconcile"
PHASE_ID = "phase-implement"
SESSION_ID = "sess-1300"

#: What the agent said as it finished. Long enough and specific enough to be a
#: conclusion rather than a sign-off - the refusal floor closed in round 2
#: rejects a bare "Done.", so a fixture that could pass on the default would
#: prove nothing about the restart.
LAST_MESSAGE = (
    "I implemented the retry budget on the check-run poller and pushed it to "
    "fix/1234-retry-budget as commit 9f31ab2. The poller now backs off to the "
    "safety-net interval after three consecutive 403s instead of hammering the "
    "API, and the existing poller tests cover both intervals. I did not change "
    "the webhook path: it has its own budget and touching both at once would "
    "have made the failure impossible to attribute."
)


@dataclass
class _Summary:
    """The read-model row reconciliation sweeps, exactly as it sweeps it."""

    workflow_execution_id: str = EXECUTION_ID
    completed_phases: int = 0
    total_phases: int = 3
    started_at: datetime = datetime(2026, 9, 3, 3, 15, tzinfo=UTC)


class _StubExecutionList:
    def __init__(self, rows: Sequence[_Summary]) -> None:
        self._rows = list(rows)

    async def get_all(
        self, limit: int = 100, offset: int = 0, status_filter: str | None = None
    ) -> list[_Summary]:
        return self._rows[offset : offset + limit]


class _StubManager:
    def __init__(self, rows: Sequence[_Summary]) -> None:
        self.workflow_execution_list = _StubExecutionList(rows)


class _EventStore:
    """An execution repository that keeps events and rebuilds only from them.

    `get_by_id` never hands back an object anyone has held before, so any state
    reconciliation finds on it came out of the stream. That IS the restart.
    """

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.envelopes.extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        if not self.envelopes:
            return None
        revived = WorkflowExecutionAggregate()
        revived.rehydrate(self.envelopes)
        return revived

    def events_named(self, event_type: str) -> list[Any]:
        return [
            envelope.event
            for envelope in self.envelopes
            if getattr(envelope.event, "event_type", type(envelope.event).__name__) == event_type
        ]


class _ArtifactRepository:
    """Where a salvaged deliverable lands, kept so the test can read it back."""

    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def save(self, aggregate: Any) -> None:
        self.saved.append(aggregate)

    async def save_new(self, aggregate: Any) -> None:
        await self.save(aggregate)


async def _stranded_stream() -> _EventStore:
    """An execution a restart caught between agent completion and collection.

    Built by commanding a real aggregate, so the stream is one production
    could actually have written rather than handmade envelopes.
    """
    store = _EventStore()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            workflow_name="sdlc-implement",
            total_phases=3,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            phase_id=PHASE_ID,
            phase_name="implement",
            phase_order=1,
            session_id=SESSION_ID,
        )
    )
    aggregate.provision_workspace_completed(
        ProvisionWorkspaceCompletedCommand(
            execution_id=EXECUTION_ID,
            phase_id=PHASE_ID,
            workspace_id="ws-1300",
            session_id=SESSION_ID,
        )
    )
    aggregate.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id=EXECUTION_ID,
            phase_id=PHASE_ID,
            session_id=SESSION_ID,
            exit_code=0,
            input_tokens=120_000,
            output_tokens=9_000,
            last_agent_message=LAST_MESSAGE,
        )
    )
    await store.save(aggregate)
    # And then the process died. No ArtifactsCollectedForPhase, no
    # PhaseCompleted - which is the whole situation.
    return store


def _install(
    monkeypatch: pytest.MonkeyPatch,
    store: _EventStore,
    artifacts: _ArtifactRepository,
    rows: Sequence[_Summary] = (_Summary(),),
) -> None:
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", lambda: _StubManager(rows))
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_workflow_execution_repository",
        lambda: store,
    )
    # The real `_artifact_collector` is left alone on purpose: patching it
    # would skip the wiring this fix depends on. Only its two leaves are
    # replaced, and object storage is None - the salvage must not need it.
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_artifact_repository",
        lambda: artifacts,
    )

    async def _no_object_storage() -> None:
        return None

    monkeypatch.setattr(
        "syn_adapters.storage.artifact_storage.get_artifact_storage", _no_object_storage
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_restart_before_collection_still_yields_the_deliverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the door production uses, not the one tests prefer.

    The assertion is about what SURVIVES: an artifact holding what the agent
    concluded, a PhaseCompleted that says the deliverable was recovered, and a
    phase that is completed rather than swept away with the run.
    """
    store = await _stranded_stream()
    artifacts = _ArtifactRepository()
    _install(monkeypatch, store, artifacts)

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert len(artifacts.saved) == 1, "the finished phase's deliverable was discarded"
    stored = artifacts.saved[0]
    assert "9f31ab2" in stored.content, "the artifact is not what the agent actually said"
    assert stored.phase_id == PHASE_ID

    completed = store.events_named("PhaseCompleted")
    assert len(completed) == 1, "the phase was not completed, so nothing points at the artifact"
    assert completed[0].deliverable_recovered is True
    assert completed[0].artifact_id == stored.aggregate_id

    collected = store.events_named("ArtifactsCollectedForPhase")
    assert collected and collected[0].deliverable_recovered is True


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_execution_still_ends_and_says_the_phase_was_rescued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run does not come back to life; only its finished phase survives.

    Nothing can execute the two remaining phases - no processor, no container -
    so the execution must still be closed, and #1120's guarantee is untouched.
    The failure reason has to say a deliverable was kept, or an operator reads
    'orphaned' and goes looking for work that is actually sitting in the store.
    """
    store = await _stranded_stream()
    _install(monkeypatch, store, _ArtifactRepository())

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    failed = store.events_named("WorkflowFailed")
    assert len(failed) == 1
    assert "recovered from the transcript" in failed[0].error_message
    # Not the rescued phase: it completed. Naming it here would have both phase
    # read models terminalise a phase that succeeded (#1036).
    assert failed[0].failed_phase_id is None


@pytest.mark.unit
@pytest.mark.anyio
async def test_an_execution_with_nothing_to_salvage_is_failed_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The salvage is not a licence to keep zombies alive.

    A phase whose agent never finished has no conclusion to recover, so this
    must behave exactly as it did before #1300: no artifact, no PhaseCompleted,
    and the execution failed naming the phase it died in.
    """
    store = _EventStore()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            workflow_name="sdlc-implement",
            total_phases=3,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            phase_id=PHASE_ID,
            phase_name="implement",
            phase_order=1,
            session_id=SESSION_ID,
        )
    )
    await store.save(aggregate)
    artifacts = _ArtifactRepository()
    _install(monkeypatch, store, artifacts)

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert artifacts.saved == []
    assert store.events_named("PhaseCompleted") == []
    failed = store.events_named("WorkflowFailed")
    assert len(failed) == 1
    assert failed[0].failed_phase_id == PHASE_ID
    assert "recovered from the transcript" not in failed[0].error_message
