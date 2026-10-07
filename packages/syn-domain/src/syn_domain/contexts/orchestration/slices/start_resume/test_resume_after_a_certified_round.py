"""A resume of a run that already certified keeps the rounds it skipped (#1681).

The parent certifies at `reverify`, skips `fix_2` through `reverify_3`, and
then fails in `finalize_pr`. Before this the resume stopped its inherited
prefix at `fix_2`, as if a skipped round were unfinished work: the child re-ran
three phases the review had made unnecessary, and its progress counted them as
still to do.

Driven through the real aggregate: the parent's stream is written through JSON
and loaded fresh before the resume is decided and again before the child's
start is built, so every decision here is one a restart rebuilds. The child's
events then go into empty list and detail read models twice, because a rebuild
is how every deployment reaches them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    FailureClassification,
    PhaseDefinition,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.phase_progress import (
        PhaseProgress,
    )

pytestmark = pytest.mark.unit

PARENT = "exec-certified-parent"
CHILD = "exec-certified-child"
WORKFLOW = "wf-rounds"
PHASES = (
    "premise",
    "implement",
    "verify",
    "fix",
    "reverify",
    "fix_2",
    "reverify_2",
    "fix_3",
    "reverify_3",
    "finalize_pr",
)
SKIPPED = ["fix_2", "reverify_2", "fix_3", "reverify_3"]
CERTIFIED_PREFIX = list(PHASES[: PHASES.index("fix_2")])
DEFINITIONS = [PhaseDefinition(phase_id=p, name=p, order=i + 1) for i, p in enumerate(PHASES)]
PINNED = [
    ExecutablePhase(
        phase_id=p,
        name=p,
        order=i + 1,
        agent_config=AgentConfiguration(),
        prompt_template=p,
        output_artifact_types=(),
        timeout_seconds=1800,
    )
    for i, p in enumerate(PHASES)
]


class _Store:
    """Append-only, and read back through JSON into a fresh aggregate."""

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

    def of_type[E: DomainEvent](self, kind: type[E]) -> list[E]:
        return [e.event for e in self.events if isinstance(e.event, kind)]


def _run_phase(store: _Store, phase_id: str, verdict: str | None) -> str | None:
    """Run one phase to completion and return the phase the aggregate chose next."""
    aggregate = store.load()
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id=WORKFLOW,
            phase_id=phase_id,
            phase_name=phase_id,
            phase_order=PHASES.index(phase_id) + 1,
        )
    )
    aggregate.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id=PARENT,
            phase_id=phase_id,
            session_id="s",
            reported_review_verdict=ReviewVerdict.from_reported(verdict),
        )
    )
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(execution_id=PARENT, phase_id=phase_id, artifact_ids=[])
    )
    decisions_before = len(store.of_type(NextPhaseReadyEvent))
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=PARENT,
            workflow_id=WORKFLOW,
            phase_id=phase_id,
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
    store.save(aggregate)
    decided = store.of_type(NextPhaseReadyEvent)[decisions_before:]
    return decided[0].next_phase_id if decided else None


def _certified_then_failed_in_finalize() -> _Store:
    """The parent: certified at `reverify`, then failed in `finalize_pr`."""
    store = _Store()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id=WORKFLOW,
            workflow_name="rounds",
            total_phases=len(PHASES),
            inputs={},
            phase_definitions=DEFINITIONS,
            pinned_phases=PINNED,
        )
    )
    store.save(aggregate)
    phase_id: str | None = PHASES[0]
    while phase_id is not None and phase_id != "finalize_pr":
        phase_id = _run_phase(store, phase_id, "certified" if phase_id == "reverify" else None)
    assert phase_id == "finalize_pr"
    aggregate = store.load()
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id=WORKFLOW,
            phase_id="finalize_pr",
            phase_name="finalize_pr",
            phase_order=len(PHASES),
        )
    )
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="push refused",
            error_type=None,
            failed_phase_id="finalize_pr",
            completed_phases=len(CERTIFIED_PREFIX),
            total_phases=len(PHASES),
            classification=FailureClassification.PLATFORM,
        )
    )
    store.save(aggregate)
    return store


def _resume(store: _Store) -> tuple[ExecutionResumedEvent, list[DomainEvent]]:
    """Admit the resume on the parent, then start the child from the parent's stream."""
    parent = store.load()
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=PARENT,
            resume_execution_id=CHILD,
            acknowledge_external_effects=True,
        )
    )
    store.save(parent)
    (resumed,) = store.of_type(ExecutionResumedEvent)
    child = WorkflowExecutionAggregate()
    child.start_resume(store.load().resume_start_command())
    child_events = [
        type(e.event).model_validate_json(e.event.model_dump_json())
        for e in child.get_uncommitted_events()
    ]
    return resumed, child_events


async def _views(events: list[DomainEvent]) -> tuple[PhaseProgress, PhaseProgress]:
    """List and detail progress after applying the child's events to empty stores."""
    store = InMemoryProjectionStore()
    listing = WorkflowExecutionListProjection(store)
    detail = WorkflowExecutionDetailProjection(store)
    for event in events:
        payload = event.model_dump(mode="json")
        await listing.on_workflow_execution_started(payload)
        await detail.on_workflow_execution_started(payload)
    summary = await listing.get_by_id(CHILD)
    shown = await detail.get_by_id(CHILD)
    assert summary is not None
    assert shown is not None
    return summary.phase_progress, shown.phase_progress


class TestAResumeKeepsTheRoundsItsParentSkipped:
    def test_the_resume_starts_at_finalize_not_at_the_skipped_round(self) -> None:
        resumed, _ = _resume(_certified_then_failed_in_finalize())

        assert resumed.resume_phase_id == "finalize_pr"
        assert [p.phase_id for p in resumed.inherited_phases] == CERTIFIED_PREFIX
        assert resumed.inherited_skipped_phase_ids == SKIPPED

    def test_the_child_start_carries_the_skips_through_json(self) -> None:
        _, (started,) = _resume(_certified_then_failed_in_finalize())

        assert started.model_dump(mode="json")["inherited_skipped_phase_ids"] == SKIPPED

    async def test_both_views_show_the_child_at_its_last_phase_and_agree_on_replay(
        self,
    ) -> None:
        _, child_events = _resume(_certified_then_failed_in_finalize())

        first = await _views(child_events)
        replayed = await _views(child_events)

        listed, detailed = first
        assert listed == detailed
        assert (listed.completed, listed.skipped, listed.defined) == (5, 4, 10)
        assert replayed == first

    def test_a_resume_of_the_resume_still_passes_over_the_skipped_round(self) -> None:
        """The child holds its parent's skips as its own, so its own resume
        inherits the same prefix and the same skips, not a gap at `fix_2`."""
        store = _certified_then_failed_in_finalize()
        _resume(store)
        child = WorkflowExecutionAggregate()
        child.start_resume(store.load().resume_start_command())
        child.start_phase(
            StartPhaseCommand(
                execution_id=CHILD,
                workflow_id=WORKFLOW,
                phase_id="finalize_pr",
                phase_name="finalize_pr",
                phase_order=len(PHASES),
            )
        )
        child.fail_execution(
            FailExecutionCommand(
                execution_id=CHILD,
                error="push refused again",
                error_type=None,
                failed_phase_id="finalize_pr",
                completed_phases=len(CERTIFIED_PREFIX),
                total_phases=len(PHASES),
                classification=FailureClassification.PLATFORM,
            )
        )
        child_store = _Store()
        child_store.save(child)
        reloaded = child_store.load()
        reloaded.resume_execution(
            ResumeExecutionCommand(
                execution_id=CHILD,
                resume_execution_id="exec-grandchild",
                acknowledge_external_effects=True,
            )
        )
        child_store.save(reloaded)

        (again,) = child_store.of_type(ExecutionResumedEvent)
        assert again.resume_phase_id == "finalize_pr"
        assert again.inherited_skipped_phase_ids == SKIPPED

    def test_a_fresh_resume_writes_no_skips_key(self) -> None:
        """A resume with nothing skipped writes the event exactly as before."""
        resumed = ExecutionResumedEvent(
            workflow_id=WORKFLOW,
            execution_id=PARENT,
            resume_execution_id=CHILD,
            inherited_phases=[],
            resume_phase_id="premise",
            resumed_at=datetime.now(UTC),
        )

        assert "inherited_skipped_phase_ids" not in resumed.model_dump(mode="json")
