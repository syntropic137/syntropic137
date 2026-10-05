"""The aggregate, not the prompts, decides how many repair rounds run (PC-63).

Drives the aggregate the way the processor does: run whatever phase the last
`NextPhaseReady` named, report the agent's TASK_RESULT through the same reader
production uses, and collect. Between the agent finishing and its artifacts
being collected the stream is written through JSON and loaded into a FRESH
aggregate, so every decision below is one a restart rebuilds from the stream -
the verdict is never in process memory when the choice is made.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
    next_phase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CompleteExecutionCommand,
    CompletePhaseCommand,
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
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
)

pytestmark = pytest.mark.unit

EXECUTION = "exec-rounds"
#: The shape of workflows/sdlc/implement-v3: three fix/reverify rounds.
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
DEFINITIONS = [PhaseDefinition(phase_id=p, name=p, order=i + 1) for i, p in enumerate(PHASES)]


def _said(verdict: str | None) -> str:
    """The closing message an agent writes, with or without a review verdict."""
    extra = "" if verdict is None else f', "review_verdict": "{verdict}"'
    return f'TASK_RESULT: {{"success": true, "side_effects": "none"{extra}}}\nTASK_RESULT_END'


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


def _run(verdicts: dict[str, str]) -> tuple[list[str], _Store]:
    """Run to completion, each phase reporting the verdict ``verdicts`` gives it."""
    store = _Store()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            workflow_name="rounds",
            total_phases=len(PHASES),
            inputs={},
            phase_definitions=DEFINITIONS,
        )
    )
    store.save(aggregate)
    ran: list[str] = []
    phase_id: str | None = PHASES[0]
    while phase_id is not None:
        ran.append(phase_id)
        aggregate.start_phase(
            StartPhaseCommand(
                execution_id=EXECUTION,
                workflow_id="wf",
                phase_id=phase_id,
                phase_name=phase_id,
                phase_order=PHASES.index(phase_id) + 1,
            )
        )
        verdict = AgentVerdict.from_agent_text(_said(verdicts.get(phase_id)))
        aggregate.agent_execution_completed(
            AgentExecutionCompletedCommand(
                execution_id=EXECUTION,
                phase_id=phase_id,
                session_id="s",
                reported_review_verdict=verdict.reported_review_verdict,
            )
        )
        store.save(aggregate)
        aggregate = store.load()  # a restart between the agent and collection
        decisions_before = len(store.of_type(NextPhaseReadyEvent))
        aggregate.artifacts_collected(
            ArtifactsCollectedCommand(execution_id=EXECUTION, phase_id=phase_id, artifact_ids=[])
        )
        aggregate.complete_phase(
            CompletePhaseCommand(
                execution_id=EXECUTION,
                workflow_id="wf",
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
        phase_id = decided[0].next_phase_id if decided else None
    aggregate = store.load()
    aggregate.complete_execution(
        CompleteExecutionCommand(
            execution_id=EXECUTION,
            completed_phases=len(ran),
            total_phases=len(PHASES),
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            duration_seconds=1.0,
            artifact_ids=[],
        )
    )
    store.save(aggregate)
    return ran, store


def _ended_on(store: _Store) -> ReviewVerdict | None:
    (completed,) = store.of_type(WorkflowCompletedEvent)
    return completed.review_verdict


class TestRepairRoundsAreDecidedByTheAggregate:
    def test_round_one_certifies_and_no_extra_round_runs(self) -> None:
        ran, store = _run({"reverify": "certified"})

        assert ran == ["premise", "implement", "verify", "fix", "reverify", "finalize_pr"]
        skipped = [d.skipped_phase_ids for d in store.of_type(NextPhaseReadyEvent)]
        assert ["fix_2", "reverify_2", "fix_3", "reverify_3"] in skipped
        assert _ended_on(store) is ReviewVerdict.CERTIFIED

    def test_blocked_blocked_certified_runs_three_rounds_then_finalizes_certified(self) -> None:
        ran, store = _run(
            {"reverify": "blocked", "reverify_2": "blocked", "reverify_3": "certified"}
        )

        assert ran == list(PHASES)
        assert _ended_on(store) is ReviewVerdict.CERTIFIED

    def test_round_two_certifies_and_round_three_is_skipped(self) -> None:
        ran, _ = _run({"reverify": "blocked", "reverify_2": "certified"})

        assert "fix_3" not in ran
        assert "reverify_3" not in ran
        assert ran[-1] == "finalize_pr"

    def test_blocked_three_times_stops_at_the_bound_with_unresolved_findings(self) -> None:
        ran, store = _run({"reverify": "blocked", "reverify_2": "blocked", "reverify_3": "blocked"})

        assert ran == list(PHASES)
        assert _ended_on(store) is ReviewVerdict.BLOCKED
        assert store.load().review_verdict is ReviewVerdict.BLOCKED

    def test_a_misspelled_verdict_never_skips_a_round(self) -> None:
        """Only an exact ``certified`` skips; anything else is no verdict."""
        ran, store = _run({"reverify": "Certified", "reverify_2": "blocked"})

        assert ran == list(PHASES)
        assert _ended_on(store) is ReviewVerdict.BLOCKED

    def test_a_run_with_no_review_records_no_verdict(self) -> None:
        ran, store = _run({})

        assert ran == list(PHASES)
        assert _ended_on(store) is None

    def test_replaying_the_stream_rebuilds_the_same_decision(self) -> None:
        """`_run` collects every phase on an aggregate loaded fresh from the
        stream, so the decision below was made from replayed state alone; a
        second replay of the finished stream rebuilds the same outcome."""
        _, store = _run({"reverify": "blocked", "reverify_2": "certified"})

        after_round_two = [
            d for d in store.of_type(NextPhaseReadyEvent) if d.completed_phase_id == "reverify_2"
        ]
        assert [d.next_phase_id for d in after_round_two] == ["finalize_pr"]
        assert store.load().review_verdict is ReviewVerdict.CERTIFIED


def _resume(store: _Store, *, acknowledge_external_effects: bool = True) -> ExecutionResumedEvent:
    """Ask the finished run, loaded from its stream, for a resume."""
    parent = store.load()
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=EXECUTION,
            resume_execution_id="exec-rounds-continued",
            acknowledge_external_effects=acknowledge_external_effects,
        )
    )
    store.save(parent)
    (resumed,) = store.of_type(ExecutionResumedEvent)
    return resumed


class TestUnresolvedFindingsAreResumable:
    """A run blocked at the bound completes, and continues at its last fix."""

    def test_resumes_at_the_last_rounds_fix_inheriting_everything_before_it(self) -> None:
        _, store = _run({"reverify": "blocked", "reverify_2": "blocked", "reverify_3": "blocked"})

        resumed = _resume(store)

        assert resumed.resume_phase_id == "fix_3"
        assert [p.phase_id for p in resumed.inherited_phases] == list(
            PHASES[: PHASES.index("fix_3")]
        )
        assert resumed.external_effects_acknowledged

    def test_the_rerun_fix_may_have_pushed_so_it_needs_acknowledgement(self) -> None:
        _, store = _run({"reverify": "blocked", "reverify_2": "blocked", "reverify_3": "blocked"})

        with pytest.raises(ValueError, match="phase fix_3 started"):
            _resume(store, acknowledge_external_effects=False)

    @pytest.mark.parametrize(
        "verdicts",
        [{"reverify": "certified"}, {"reverify": "blocked", "reverify_2": "certified"}, {}],
        ids=["certified-round-1", "certified-round-2", "no-review"],
    )
    def test_a_completed_run_without_unresolved_findings_is_not_resumable(
        self, verdicts: dict[str, str]
    ) -> None:
        _, store = _run(verdicts)

        with pytest.raises(ValueError, match="Cannot resume execution in status completed"):
            _resume(store)


class TestNextPhase:
    def test_the_final_phase_is_never_skipped_and_has_no_successor(self) -> None:
        assert next_phase(DEFINITIONS, len(PHASES), ReviewVerdict.CERTIFIED) is None

    def test_certified_on_the_last_round_skips_nothing(self) -> None:
        decided = next_phase(DEFINITIONS, PHASES.index("reverify_3") + 1, ReviewVerdict.CERTIFIED)
        assert decided is not None
        assert decided.phase.phase_id == "finalize_pr"
        assert decided.skipped == ()
