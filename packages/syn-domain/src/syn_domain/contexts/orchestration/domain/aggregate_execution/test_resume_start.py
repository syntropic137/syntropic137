"""The child a resume admitted, as its own stream records it (ADR-014 s7, #1454).

As in `test_resume`, every assertion is made against an aggregate READ BACK
through JSON, because that is the only aggregate a later request ever has:
what the parent pinned and what the child inherited are worth nothing if they
do not survive the store.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from event_sourcing import DomainEvent, EventEnvelope, GenericDomainEvent
from pydantic import ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_start import (
    refuse_resume_start,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    SourceCommit,
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionStatus,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    StartResumeCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)

pytestmark = pytest.mark.unit

PARENT = "exec-parent"
RESUME = "exec-resume"
PHASE_IDS = ("research", "plan", "implement")
COMMIT = SourceCommit(repository="acme/widgets", sha="0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c")


def _pinned() -> list[ExecutablePhase]:
    """Each phase configured the way no template default would produce."""
    return [
        ExecutablePhase(
            phase_id=p,
            name=p.title(),
            order=i + 1,
            agent_config=AgentConfiguration(model=f"model-for-{p}"),
            prompt_template=f"{p} as pinned",
            timeout_seconds=600 * (i + 1),
        )
        for i, p in enumerate(PHASE_IDS)
    ]


class _Stream:
    """One aggregate's events, read back through JSON into a fresh aggregate."""

    def __init__(self) -> None:
        self.events: list[EventEnvelope[DomainEvent]] = []

    def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(
            EventEnvelope(
                event=type(e.event).model_validate_json(e.event.model_dump_json()),
                metadata=e.metadata,
            )
            for e in aggregate.get_uncommitted_events()
        )
        aggregate.mark_events_as_committed()

    def load(self) -> WorkflowExecutionAggregate:
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.events))
        return fresh


def _run_research(aggregate: WorkflowExecutionAggregate) -> None:
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            phase_name="Research",
            phase_order=1,
        )
    )
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=PARENT, phase_id="research", artifact_ids=["art-research"]
        )
    )
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            session_id=None,
            artifact_id=None,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=1.0,
        )
    )


def _resumed_parent(
    *, pinned: list[ExecutablePhase] | None, workflow_version: str | None = None
) -> _Stream:
    """A parent that completed research and failed before plan, then resumed."""
    parent = WorkflowExecutionAggregate()
    phases = _pinned()
    parent.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Resume start",
            total_phases=len(phases),
            inputs={"task": "resume me"},
            phase_definitions=phase_definitions_of(phases),
            pinned_phases=pinned,
            source_commits=[COMMIT],
            workflow_version=workflow_version,
        )
    )
    _run_research(parent)
    parent.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="boom",
            error_type="AgentError",
            failed_phase_id=None,
            completed_phases=1,
            total_phases=len(phases),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    parent.resume_execution(ResumeExecutionCommand(execution_id=PARENT, resume_execution_id=RESUME))
    stream = _Stream()
    stream.save(parent)
    return stream


def _started_child() -> _Stream:
    command = _resumed_parent(pinned=_pinned()).load().resume_start_command()
    child = WorkflowExecutionAggregate()
    child.start_resume(command)
    stream = _Stream()
    stream.save(child)
    return stream


class TestTheParentPinsWhatItStartedWith:
    def test_the_full_phase_config_survives_the_store(self) -> None:
        command = _resumed_parent(pinned=_pinned()).load().resume_start_command()

        assert command.pinned_phases == _pinned()
        assert command.source_commits == [COMMIT]
        assert command.inputs == {"task": "resume me"}

    def test_the_child_start_names_the_decision_it_carries_out(self) -> None:
        command = _resumed_parent(pinned=_pinned()).load().resume_start_command()

        assert command.aggregate_id == RESUME
        assert command.resumed_from.parent_execution_id == PARENT
        assert [p.phase_id for p in command.resumed_from.inherited_phases] == ["research"]
        assert command.resumed_from.inherited_phases[0].artifact_ids == ["art-research"]
        assert command.resumed_from.resume_phase_id == "plan"

    def test_the_child_carries_the_parents_workflow_version(self) -> None:
        """Evals v2: a resume is a new run with KNOWN provenance - its parent's."""
        parent = _resumed_parent(pinned=_pinned(), workflow_version="1.2.3").load()
        command = parent.resume_start_command()
        child = WorkflowExecutionAggregate()
        child.start_resume(command)
        stream = _Stream()
        stream.save(child)

        [started] = [
            e.event for e in stream.events if isinstance(e.event, WorkflowExecutionStartedEvent)
        ]
        assert started.workflow_version == "1.2.3"
        assert stream.load().start_pins.workflow_version == "1.2.3"

    def test_a_parent_with_no_known_version_gives_the_child_none(self) -> None:
        command = _resumed_parent(pinned=_pinned()).load().resume_start_command()

        assert command.workflow_version is None

    def test_a_parent_that_admitted_no_resume_builds_no_start(self) -> None:
        parent = WorkflowExecutionAggregate()
        parent.start_execution(
            StartExecutionCommand(
                execution_id=PARENT,
                workflow_id="wf-1",
                workflow_name="Resume start",
                total_phases=3,
                inputs={},
                pinned_phases=_pinned(),
            )
        )

        with pytest.raises(ValueError, match="has not admitted a resume"):
            parent.resume_start_command()


class TestTheChildStream:
    def test_it_is_running_with_its_inheritance_closed(self) -> None:
        child = _started_child().load()

        assert child.id == RESUME
        assert child.status is ExecutionStatus.RUNNING
        with pytest.raises(ValueError, match="research: it has already completed"):
            child.start_phase(
                StartPhaseCommand(
                    execution_id=RESUME,
                    workflow_id="wf-1",
                    phase_id="research",
                    phase_name="Research",
                    phase_order=1,
                )
            )

    def test_the_resume_phase_is_open(self) -> None:
        child = _started_child().load()

        child.start_phase(
            StartPhaseCommand(
                execution_id=RESUME,
                workflow_id="wf-1",
                phase_id="plan",
                phase_name="Plan",
                phase_order=2,
            )
        )

        assert child.running_phase_id == "plan"

    def test_it_pins_the_parents_config_again_so_it_can_be_resumed_too(self) -> None:
        pins = _started_child().load().start_pins

        assert pins.pinned_phases == _pinned()
        assert pins.source_commits == [COMMIT]
        assert pins.resumed_from is not None
        assert pins.resumed_from.parent_execution_id == PARENT

    def test_a_second_start_on_the_same_stream_is_refused(self) -> None:
        stream = _started_child()
        command = _resumed_parent(pinned=_pinned()).load().resume_start_command()

        with pytest.raises(ValueError, match="already started"):
            stream.load().start_resume(command)


class TestReplayedGenerically:
    """ADR-023: an event that fails typed validation replays as plain data."""

    def _as_generic(self, stream: _Stream, **changes: object) -> WorkflowExecutionAggregate:
        envelopes: list[EventEnvelope[DomainEvent]] = []
        for envelope in stream.events:
            if isinstance(envelope.event, WorkflowExecutionStartedEvent):
                payload = envelope.event.model_dump(mode="json")
                payload.update(changes)
                event: DomainEvent = GenericDomainEvent(
                    event_type="WorkflowExecutionStarted", **payload
                )
                envelopes.append(EventEnvelope(event=event, metadata=envelope.metadata))
            else:
                envelopes.append(envelope)
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(envelopes)
        return fresh

    def test_the_inheritance_still_closes_the_inherited_phase(self) -> None:
        child = self._as_generic(_started_child())

        assert child.start_pins.pinned_phases == _pinned()
        with pytest.raises(ValueError, match="already completed"):
            child.start_phase(
                StartPhaseCommand(
                    execution_id=RESUME,
                    workflow_id="wf-1",
                    phase_id="research",
                    phase_name="Research",
                    phase_order=1,
                )
            )

    def test_an_unreadable_origin_fails_closed(self) -> None:
        """Read as "not a resume", the child would reopen what it inherited."""
        with pytest.raises(ValidationError):
            self._as_generic(_started_child(), resumed_from={"parent_execution_id": PARENT})


class TestTheChildRefusesASnapshotThatDoesNotMatch:
    def _command(self) -> StartResumeCommand:
        return _resumed_parent(pinned=_pinned()).load().resume_start_command()

    def test_a_parent_that_pinned_nothing(self) -> None:
        command = _resumed_parent(pinned=None).load().resume_start_command()

        with pytest.raises(ValueError, match="recorded no pinned phase config"):
            WorkflowExecutionAggregate().start_resume(command)

    def test_an_inherited_phase_absent_from_the_snapshot(self) -> None:
        command = self._command()
        command.pinned_phases = [p for p in command.pinned_phases if p.phase_id != "research"]

        with pytest.raises(ValueError, match=r"inherited phase\(s\) \['research'\] are absent"):
            WorkflowExecutionAggregate().start_resume(command)

    def test_a_resume_phase_absent_from_the_snapshot(self) -> None:
        command = self._command()
        command.pinned_phases = [p for p in command.pinned_phases if p.phase_id != "plan"]

        assert refuse_resume_start(command) == (
            f"Cannot start resume {RESUME}: resume phase 'plan' is absent from the pinned phase config"
        )

    def test_a_snapshot_with_a_phase_the_inheritance_skips(self) -> None:
        """A phase between the inherited ones and the resume one would never run."""
        command = self._command()
        extra = replace(command.pinned_phases[0], phase_id="review", name="Review", order=2)
        command.pinned_phases = [
            command.pinned_phases[0],
            extra,
            *(replace(p, order=p.order + 1) for p in command.pinned_phases[1:]),
        ]

        with pytest.raises(ValueError, match="are not the pinned phases before 'plan'"):
            WorkflowExecutionAggregate().start_resume(command)

    def test_nothing_is_recorded_for_a_refused_start(self) -> None:
        command = _resumed_parent(pinned=None).load().resume_start_command()
        child = WorkflowExecutionAggregate()

        with pytest.raises(ValueError):
            child.start_resume(command)

        assert child.id is None
        assert child.get_uncommitted_events() == []
