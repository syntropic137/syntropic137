"""A workspace kept for unproven work is a fact on its execution's stream (#2321).

Every assertion reads the stream back the way production does: each event goes
through its JSON and is resolved by its registered type before a fresh
aggregate replays it. A field the command, the event or the replay drops shows
up as a wrong value, not as a passing object at either end.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope, resolve_event_type

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
    ProvisionWorkspaceCompletedCommand,
    RecordWorkspaceRetainedCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkspaceRetentionValueObjects import (
    WORK_UNPROVEN,
    RetainedReason,
)
from syn_domain.contexts.orchestration.domain.events.PhaseWorkspaceRetainedEvent import (
    PhaseWorkspaceRetainedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import orphaned_workspace
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    QuarantinedWork,
    SavedWork,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.orphaned_workspace import (
    OrphanedWorkspace,
    Retained,
    guard_orphaned_workspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.retained_workspace_record import (
    RetainedWorkspaceRecorder,
)

pytestmark = pytest.mark.unit

#: Shared with the API-side consumer tests, which drive the real guards over it.
EXECUTION = "exec-2321"


class JsonStream:
    """One execution's stream, stored as JSON and replayed into a fresh aggregate."""

    def __init__(self) -> None:
        self.events: list[EventEnvelope[DomainEvent]] = []
        self.loads = 0

    async def get_by_id(self, execution_id: str, /) -> WorkflowExecutionAggregate | None:
        self.loads += 1
        if execution_id != EXECUTION or not self.events:
            return None
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.events))
        return fresh

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        for envelope in aggregate.get_uncommitted_events():
            concrete = resolve_event_type(envelope.event.event_type)
            assert concrete is not None, envelope.event.event_type
            metadata = envelope.metadata.model_copy(
                update={"event_type": envelope.event.event_type}
            )
            stored = concrete.model_validate_json(envelope.event.model_dump_json())
            self.events.append(EventEnvelope(event=stored, metadata=metadata))
        aggregate.mark_events_as_committed()

    def retained(self) -> list[PhaseWorkspaceRetainedEvent]:
        return [e.event for e in self.events if isinstance(e.event, PhaseWorkspaceRetainedEvent)]


async def started_stream(*, cancelled: bool = False) -> JsonStream:
    """An execution whose phase `build` was provisioned workspace `ws-build`."""
    stream = JsonStream()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf-2321",
            workflow_name="Retained",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id="wf-2321",
            phase_id="build",
            phase_name="Build",
            phase_order=1,
        )
    )
    aggregate.provision_workspace_completed(
        ProvisionWorkspaceCompletedCommand(
            execution_id=EXECUTION, phase_id="build", workspace_id="ws-build"
        )
    )
    if cancelled:
        aggregate.cancel_execution(CancelExecutionCommand(EXECUTION, "build"))
    await stream.save(aggregate)
    return stream


@pytest.mark.parametrize("reason", sorted(WORK_UNPROVEN))
async def test_a_kept_workspace_is_one_event_naming_its_phase_and_reason(
    reason: RetainedReason,
) -> None:
    stream = await started_stream()
    recorder = RetainedWorkspaceRecorder(lambda: stream)

    await recorder.record(EXECUTION, "ws-build", Retained(reason, f"why: {reason.value}"))

    [event] = stream.retained()
    assert event.execution_id == EXECUTION
    assert event.workflow_id == "wf-2321"
    # Read off the stream's own provisioning: the guard never knew it.
    assert event.phase_id == "build"
    assert event.workspace_handle == "ws-build"
    assert event.reason is reason
    assert event.detail == f"why: {reason.value}"


async def test_a_pass_that_keeps_it_again_adds_nothing_even_after_a_restart() -> None:
    """The reclaimer keeps the same directory on every pass; the stream says it once."""
    stream = await started_stream()
    recorder = RetainedWorkspaceRecorder(lambda: stream)
    dirty = Retained(RetainedReason.DIRTY, "app has uncommitted changes")

    await recorder.record(EXECUTION, "ws-build", dirty)
    await recorder.record(EXECUTION, "ws-build", dirty)
    await recorder.record(EXECUTION, "ws-build", Retained(RetainedReason.STASH, "a stash"))

    assert [e.reason for e in stream.retained()] == [RetainedReason.DIRTY, RetainedReason.STASH]


async def test_it_is_accepted_after_the_run_ended() -> None:
    """A reclaimer only ever reaches a terminal run, so terminal must accept it."""
    stream = await started_stream(cancelled=True)

    await RetainedWorkspaceRecorder(lambda: stream).record(
        EXECUTION, "ws-build", Retained(RetainedReason.UNPUSHED_UNPROVEN, "2 commits")
    )

    assert [e.reason for e in stream.retained()] == [RetainedReason.UNPUSHED_UNPROVEN]


async def test_a_workspace_the_stream_never_provisioned_names_no_phase() -> None:
    stream = await started_stream()

    await RetainedWorkspaceRecorder(lambda: stream).record(
        EXECUTION, "ws-other", Retained(RetainedReason.UNVERSIONED, "1 file")
    )

    [event] = stream.retained()
    assert (event.workspace_handle, event.phase_id) == ("ws-other", None)


@pytest.mark.parametrize(
    "reason", sorted(set(RetainedReason) - WORK_UNPROVEN), ids=lambda r: r.value
)
async def test_a_keep_that_says_nothing_about_the_work_is_not_recorded(
    reason: RetainedReason,
) -> None:
    stream = await started_stream()

    await RetainedWorkspaceRecorder(lambda: stream).record(
        EXECUTION, "ws-build", Retained(reason, "eligibility, not work")
    )

    assert stream.retained() == []
    assert stream.loads == 0


async def test_the_aggregate_refuses_a_reason_that_is_not_about_the_work() -> None:
    aggregate = await (await started_stream()).get_by_id(EXECUTION)
    assert aggregate is not None
    with pytest.raises(ValueError, match="mounted"):
        aggregate.record_workspace_retained(
            RecordWorkspaceRetainedCommand(EXECUTION, "ws-build", RetainedReason.MOUNTED, "bound")
        )


class _Refusing:
    async def get_by_id(self, execution_id: str, /) -> WorkflowExecutionAggregate | None:
        raise ConnectionError("event store down")

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        raise AssertionError("never reached")


def _unopenable() -> JsonStream:
    raise RuntimeError("no event store configured")


@pytest.mark.parametrize(
    "repository",
    [_Refusing, _unopenable, JsonStream],
    ids=["store-down", "store-unopenable", "no-stream"],
)
async def test_a_recording_failure_never_raises_into_the_guard(
    repository: object, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = RetainedWorkspaceRecorder(repository)  # type: ignore[arg-type]  # each is a factory

    await recorder.record(EXECUTION, "ws-build", Retained(RetainedReason.DIRTY, "dirty"))

    assert "ws-build" in caplog.text


def test_the_event_round_trips_through_its_registered_type() -> None:
    event = PhaseWorkspaceRetainedEvent(
        workflow_id="wf-2321",
        execution_id=EXECUTION,
        phase_id="build",
        workspace_handle="ws-build",
        reason=RetainedReason.SUBMODULE_STORE_UNPROVEN,
        detail="app holds submodule stores",
        retained_at="2026-11-23T12:00:00+00:00",  # type: ignore[arg-type]  # parsed by pydantic
    )
    concrete = resolve_event_type("PhaseWorkspaceRetained")

    assert concrete is PhaseWorkspaceRetainedEvent
    assert concrete.model_validate_json(event.model_dump_json()) == event


def test_the_event_refuses_a_field_it_does_not_declare() -> None:
    with pytest.raises(ValueError, match="host_dir"):
        PhaseWorkspaceRetainedEvent.model_validate(
            {
                "workflow_id": "wf",
                "execution_id": EXECUTION,
                "phase_id": None,
                "workspace_handle": "ws",
                "reason": "dirty",
                "detail": "d",
                "retained_at": "2026-11-23T12:00:00+00:00",
                "host_dir": "/srv/workspaces/ws",
            }
        )


# --- the orphan guard names WHY it kept a directory ---


def _orphan() -> OrphanedWorkspace:
    return OrphanedWorkspace(
        workspace=object(),  # type: ignore[arg-type]  # never executed: the walk is replaced
        workspace_id="ws-1",
        execution_id=EXECUTION,
        host_dir="/workspaces/ws-1",
    )


def _quarantined(*, landed: bool, submodules: tuple[str, ...] = ()) -> QuarantinedWork:
    return QuarantinedWork(
        repo="/workspace/repos/app",
        branch="feature",
        commit_count=1,
        files=("a.py",),
        pushed_ref="refs/syn/lost/exec-2321/orphaned-ws-1" if landed else None,
        push_error=None if landed else "403 forbidden",
        unsaved_submodules=submodules,
    )


@pytest.mark.parametrize(
    ("saved", "reason"),
    [
        (SavedWork(unreadable="container gone"), RetainedReason.UNREADABLE),
        (
            SavedWork(quarantined=(_quarantined(landed=False),)),
            RetainedReason.UNPUSHED_UNPROVEN,
        ),
        (
            SavedWork(quarantined=(_quarantined(landed=True, submodules=("lib/x",)),)),
            RetainedReason.SUBMODULE_STORE_UNPROVEN,
        ),
    ],
    ids=["walk-unfinished", "push-refused", "submodule-work"],
)
async def test_each_orphan_keep_names_its_reason(
    monkeypatch: pytest.MonkeyPatch, saved: SavedWork, reason: RetainedReason
) -> None:
    async def _saved(*_args: object, **_kwargs: object) -> SavedWork:
        return saved

    monkeypatch.setattr(orphaned_workspace, "save_unpushed_work", _saved)

    verdict = await guard_orphaned_workspace(_orphan())

    assert isinstance(verdict, Retained)
    assert verdict.reason is reason
    assert reason in WORK_UNPROVEN
