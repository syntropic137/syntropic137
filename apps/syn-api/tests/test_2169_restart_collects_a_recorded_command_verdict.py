"""A restart after a command Phase recorded its verdict and before it was collected (#2169).

THE GAP. A command Phase has no agent run, so the #1300 salvage, which recovers
a deliverable from what the agent last said, never reached it: boot
reconciliation failed the run `OrphanedByRestart` (platform) even when the
stream held the steps' verdict as `PhaseCommandsCompleted`. A red build was
reported as the platform's fault, and a green one was thrown away.

WHAT IT RULES OUT. As in the #1300 test beside this one, the aggregate is
rebuilt from stored envelopes by a fresh `WorkflowExecutionAggregate`, there is
no workspace, and the result is read back out of the artifact repository and the
event stream, never off a return value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from event_sourcing import EventEnvelope

from syn_api.services.reconciliation import CleanupResult, reconcile_orphaned_executions
from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import (
    CommandStepOutcome,
    CommandStepResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.command_gate import (
    COMMAND_GATE_ERROR_TYPE,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    RecordPhaseCommandsCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.command_report import (
    COMMANDS_REPORT_PATH,
    CommandsReport,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent

    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REAPED = CleanupResult(fully_reaped=True)
_CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)
EXECUTION_ID = "exec-2169"
WORKFLOW_ID = "wf-2169"
PHASES = ("build", "review")
DEFINITIONS = [PhaseDefinition(phase_id=p, name=p, order=i + 1) for i, p in enumerate(PHASES)]

PASSED = CommandStepResult(
    name="cargo-build", outcome=CommandStepOutcome.PASSED, exit_code=0, duration_ms=1500
)
#: Exit 2, a number nothing defaults to, so the stored report can only hold it
#: if it came off the recorded event.
FAILED = CommandStepResult(
    name="wasm", outcome=CommandStepOutcome.FAILED, exit_code=2, duration_ms=1500
)


@dataclass
class _Summary:
    workflow_execution_id: str = EXECUTION_ID
    completed_phases: int = 0
    total_phases: int = len(PHASES)
    started_at: datetime = datetime(2026, 11, 9, 3, 15, tzinfo=UTC)


class _StubExecutionList:
    async def get_all(
        self, limit: int = 100, offset: int = 0, status_filter: str | None = None
    ) -> list[_Summary]:
        return [_Summary()]


class _StubManager:
    workflow_execution_list = _StubExecutionList()


class _EventStore:
    """Keeps events through JSON and rebuilds only from them: that IS the restart."""

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.envelopes.extend(
            EventEnvelope(
                event=type(e.event).model_validate_json(e.event.model_dump_json()),
                metadata=e.metadata,
            )
            for e in aggregate.get_uncommitted_events()
        )
        aggregate.mark_events_as_committed()

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        revived = WorkflowExecutionAggregate()
        revived.rehydrate(list(self.envelopes))
        return revived

    def events_named(self, event_type: str) -> list[Any]:
        return [
            envelope.event
            for envelope in self.envelopes
            if getattr(envelope.event, "event_type", type(envelope.event).__name__) == event_type
        ]


class _ArtifactRepository:
    def __init__(self) -> None:
        self.saved: list[ArtifactAggregate] = []

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def save_new(self, aggregate: ArtifactAggregate) -> None:
        await self.save(aggregate)


async def _stranded(steps: Sequence[CommandStepResult] | None, *, success: bool) -> _EventStore:
    """Command Phase `build` started; its steps recorded unless `steps` is None; then death."""
    store = _EventStore()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            workflow_name="gate",
            total_phases=len(PHASES),
            inputs={},
            phase_definitions=DEFINITIONS,
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            phase_id="build",
            phase_name="build",
            phase_order=1,
        )
    )
    if steps is not None:
        aggregate.record_phase_commands(
            RecordPhaseCommandsCommand(
                execution_id=EXECUTION_ID,
                phase_id="build",
                workspace_id="ws-2169",
                success=success,
                steps=list(steps),
            )
        )
    await store.save(aggregate)
    return store


def _install(
    monkeypatch: pytest.MonkeyPatch, store: _EventStore, artifacts: _ArtifactRepository
) -> None:
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", _StubManager)
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_workflow_execution_repository", lambda: store
    )
    # The real `_artifact_collector` runs; only its two leaves are replaced.
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_artifact_repository", lambda: artifacts
    )

    async def _no_object_storage() -> None:
        return None

    monkeypatch.setattr(
        "syn_adapters.storage.artifact_storage.get_artifact_storage", _no_object_storage
    )


def _stored_report(artifacts: _ArtifactRepository) -> CommandsReport:
    assert len(artifacts.saved) == 1, "the recorded verdict was not stored as commands.json"
    stored = artifacts.saved[0]
    assert stored.phase_id == "build"
    assert stored.source_path == COMMANDS_REPORT_PATH
    return CommandsReport.model_validate_json(stored.content)


async def test_a_red_gate_recorded_before_the_restart_fails_as_a_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _stranded([PASSED, FAILED], success=False)
    artifacts = _ArtifactRepository()
    _install(monkeypatch, store, artifacts)

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    report = _stored_report(artifacts)
    assert report.tails_lost is True
    assert report.success is False
    assert [(s.name, s.exit_code) for s in report.steps] == [
        ("cargo-build", 0),
        ("wasm", 2),
    ]

    failed = store.events_named("WorkflowFailed")
    assert len(failed) == 1, "a gate failure must not be followed by an orphan failure"
    assert failed[0].error_type == COMMAND_GATE_ERROR_TYPE
    assert failed[0].error_type != "OrphanedByRestart"
    assert failed[0].failure_classification == FailureClassification.GATE
    assert failed[0].exit_code == 2
    assert failed[0].failed_phase_id == "build"
    assert list(failed[0].failed_phase_artifact_ids) == [artifacts.saved[0].aggregate_id]
    assert store.events_named("PhaseCompleted") == []


async def test_a_green_gate_recorded_before_the_restart_completes_its_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The phase survives and its next phase is decided; the run itself still closes.

    Nothing at boot can execute `review`, the same as after an agent salvage
    (ADR-078 D6, ADR-072), so the run ends naming what was kept.
    """
    store = await _stranded([PASSED], success=True)
    artifacts = _ArtifactRepository()
    _install(monkeypatch, store, artifacts)

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    report = _stored_report(artifacts)
    assert report.tails_lost is True
    assert report.success is True

    completed = store.events_named("PhaseCompleted")
    assert len(completed) == 1, "a passed gate's phase was discarded with the run"
    assert completed[0].phase_id == "build"
    assert completed[0].artifact_id == artifacts.saved[0].aggregate_id
    ready = store.events_named("NextPhaseReady")
    assert [e.next_phase_id for e in ready] == ["review"]

    failed = store.events_named("WorkflowFailed")
    assert len(failed) == 1
    assert failed[0].error_type == "OrphanedByRestart"
    assert "commands.json was rebuilt from the event stream" in failed[0].error_message
    assert failed[0].failed_phase_id is None


async def test_a_command_phase_stranded_before_its_verdict_is_still_orphaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _stranded(None, success=False)
    artifacts = _ArtifactRepository()
    _install(monkeypatch, store, artifacts)

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert artifacts.saved == []
    assert store.events_named("PhaseCompleted") == []
    failed = store.events_named("WorkflowFailed")
    assert len(failed) == 1
    assert failed[0].error_type == "OrphanedByRestart"
    assert failed[0].failure_classification == FailureClassification.PLATFORM
    assert failed[0].failed_phase_id == "build"


async def test_a_retry_that_had_not_recorded_its_verdict_is_still_orphaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An earlier attempt's verdict is not the verdict of the attempt the restart caught."""
    store = await _stranded([PASSED], success=True)
    aggregate = await store.get_by_id(EXECUTION_ID)
    assert aggregate is not None
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            phase_id="build",
            phase_name="build",
            phase_order=1,
        )
    )
    await store.save(aggregate)
    artifacts = _ArtifactRepository()
    _install(monkeypatch, store, artifacts)

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert artifacts.saved == []
    failed = store.events_named("WorkflowFailed")
    assert [f.error_type for f in failed] == ["OrphanedByRestart"]
