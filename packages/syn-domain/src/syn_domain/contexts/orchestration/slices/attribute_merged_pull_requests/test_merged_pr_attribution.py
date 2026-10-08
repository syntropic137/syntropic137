"""#1728: a merged PR costs every run that built it, recorded live, rebuilt by replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, ProjectionResult
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPullRequestMergeCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    merge_recorded_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
    PhaseDefinition,
    ResumeOrigin,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.PullRequestMergeRecordedEvent import (
    PullRequestMergeRecordedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.attribute_merged_pull_requests import (
    MergedPullRequestAttributionProcessManager,
    PullRequestMergeState,
    RecordPullRequestMergeHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    completed_execution,
    completed_phase,
)
from syn_domain.contexts.orchestration.slices.scorecard import (
    ExecutionSpend,
    ScorecardProjection,
    compute_scorecard,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 7, 1, tzinfo=UTC)
REPO = "acme/widget"
SPEND = {"a": Decimal(1), "b": Decimal(2), "c": Decimal(4), "d": Decimal(8), "e": Decimal(16)}


def _at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


@dataclass
class _Forge:
    """GitHub as the manager sees it: PR 7 merged, PR 8 still open."""

    calls: list[int] = field(default_factory=list)

    async def read_merge(self, repository: str, pull_request: int) -> PullRequestMergeState:
        assert repository == REPO
        self.calls.append(pull_request)
        if pull_request == 7:
            return PullRequestMergeState(readable=True, merged_at=_at(10))
        return PullRequestMergeState(readable=True)


class _Unreachable:
    async def read_merge(self, repository: str, pull_request: int) -> PullRequestMergeState:
        raise AssertionError(f"replay asked GitHub about {repository}#{pull_request}")


@dataclass
class _Recorder:
    """The aggregate's side: the real event producer, appended to the log."""

    log: list[DomainEvent]

    async def record_merge(
        self, execution_id: str, repository: str, pull_request: int, merged_at: datetime
    ) -> None:
        command = RecordPullRequestMergeCommand(execution_id, repository, pull_request, merged_at)
        self.log.append(merge_recorded_event(command, "wf"))


def _envelope(event: DomainEvent, nonce: int) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="execution",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=nonce,
            event_type=event.event_type,
            global_nonce=nonce,
        ),
    )


async def _deliver(
    consumers: tuple[MergedPullRequestAttributionProcessManager, ScorecardProjection],
    events: list[DomainEvent],
) -> None:
    for nonce, event in enumerate(events, start=1):
        for consumer in consumers:
            result = await consumer.handle_event(_envelope(event, nonce), MemoryCheckpointStore())
            assert result is ProjectionResult.SUCCESS


def _started(
    execution_id: str, start: float, *, parent: str | None = None, pr: int | None = None
) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id="wf",
        execution_id=execution_id,
        workflow_name="implement",
        started_at=_at(start),
        total_phases=2,
        inputs={"repository": REPO, "pr_number": str(pr)} if pr else {},
        resumed_from=(
            ResumeOrigin(parent_execution_id=parent, inherited_phases=[], resume_phase_id="verify")
            if parent
            else None
        ),
    )


def _failed(execution_id: str, end: float, pr: int) -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id="wf",
        execution_id=execution_id,
        failed_at=_at(end),
        failed_phase_id="verify",
        error_message="phase failed",
        completed_phases=1,
        total_phases=2,
        observed_branches=[
            BranchObservation(
                repo=REPO,
                branch=f"feat/{pr}",
                remote="origin",
                remote_commit="b" * 40,
                remote_commit_at_phase_start="a" * 40,
                unpushed_commits=0,
                pull_request=pr,
            )
        ],
    )


def _completed(execution_id: str, end: float) -> WorkflowCompletedEvent:
    return WorkflowCompletedEvent(
        workflow_id="wf",
        execution_id=execution_id,
        completed_at=_at(end),
        total_phases=2,
        completed_phases=2,
        total_input_tokens=0,
        total_output_tokens=0,
        total_tokens=0,
        total_duration_seconds=1.0,
        artifact_ids=[],
    )


def _history() -> list[DomainEvent]:
    """PR 7: failed ``a``, its resume ``b``, an independent reverify ``c``.
    PR 8: failed ``d``, never merged. ``e`` touched no PR."""
    failed_a = _failed("a", 1, 7)
    return [
        _started("a", 0),
        failed_a,
        failed_a,  # redelivered
        _started("b", 2, parent="a"),
        _completed("b", 3),
        _started("c", 4, pr=7),
        _completed("c", 5),
        _started("d", 0),
        _failed("d", 1, 8),
        _started("e", 0),
        _completed("e", 1),
    ]


async def _score(projection: ScorecardProjection) -> tuple[int | None, Decimal | None]:
    merged = await projection.merged_pull_requests_for_days(["2026-10-07"])
    card = compute_scorecard(
        runs={},
        spend_by_execution={k: ExecutionSpend(total_usd=v, by_phase={}) for k, v in SPEND.items()},
        tool_calls_by_session={},
        cost_by_session_model={},
        now=_at(20),
        window_days=1,
        merged_pull_requests=merged,
    )
    return card.merged_prs, card.cost_per_merged_pr_usd


async def test_a_merged_pr_costs_its_failed_run_resume_and_reverify_once_each() -> None:
    log = _history()
    forge, recorder = _Forge(), _Recorder(log)
    manager = MergedPullRequestAttributionProcessManager(
        store=InMemoryProjectionStore(), merges=forge, recorder=recorder
    )
    scorecard = ScorecardProjection(InMemoryProjectionStore())
    await _deliver((manager, scorecard), log)

    assert await manager.process_pending() == 3
    recorded = log[len(_history()) :]
    assert sorted(e.execution_id for e in recorded) == ["a", "b", "c"]  # type: ignore[attr-defined]
    # Delivered live, and one redelivered: nobody counts twice.
    await _deliver((manager, scorecard), [*recorded, recorded[0]])

    assert await manager.process_pending() == 0  # recorded once, however often offered
    assert sorted(set(forge.calls)) == [7, 8]
    [merged] = await scorecard.merged_pull_requests_for_days(["2026-10-07"])
    assert (merged.pull_request, sorted(merged.execution_ids)) == (7, ["a", "b", "c"])
    assert await _score(scorecard) == (1, Decimal(7))  # 1 + 2 + 4; d's unmerged 8 and e excluded


async def test_replay_rebuilds_identical_numbers_without_asking_github() -> None:
    log = _history()
    manager = MergedPullRequestAttributionProcessManager(
        store=InMemoryProjectionStore(), merges=_Forge(), recorder=_Recorder(log)
    )
    scorecard = ScorecardProjection(InMemoryProjectionStore())
    await _deliver((manager, scorecard), log)
    await manager.process_pending()
    await _deliver((manager, scorecard), log[len(_history()) :])
    live = await _score(scorecard)

    replay_recorder = _Recorder([])
    replayed = MergedPullRequestAttributionProcessManager(
        store=InMemoryProjectionStore(), merges=_Unreachable(), recorder=replay_recorder
    )
    rebuilt = ScorecardProjection(InMemoryProjectionStore())
    await rebuilt.clear_all_data()
    await _deliver((replayed, rebuilt), list(log))  # catch-up: handle_event only

    assert await _score(rebuilt) == live == (1, Decimal(7))
    assert replay_recorder.log == []


@dataclass
class _Repository:
    """Saves an aggregate's events and loads it back by replaying them."""

    streams: dict[str, list[EventEnvelope[DomainEvent]]] = field(default_factory=dict)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        if aggregate_id not in self.streams:
            return None
        aggregate = WorkflowExecutionAggregate()
        aggregate.rehydrate(list(self.streams[aggregate_id]))
        return aggregate

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.streams.setdefault(str(aggregate.id), []).extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()


async def test_the_aggregate_records_a_contributor_once_per_pr() -> None:
    """Through the real handler: a retried live pass cannot record the same merge twice."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id="a",
            workflow_id="wf",
            workflow_name="implement",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="verify", name="Verify", order=1)],
        )
    )
    repository = _Repository()
    await repository.save(aggregate)
    handler = RecordPullRequestMergeHandler(repository)  # type: ignore[arg-type]

    await handler.record_merge("a", REPO, 7, _at(10))
    await handler.record_merge("a", REPO, 7, _at(10))  # the pass that crashed before its save
    await handler.record_merge("a", REPO, 9, _at(11))

    merges = [
        e.event
        for e in repository.streams["a"]
        if isinstance(e.event, PullRequestMergeRecordedEvent)
    ]
    assert [(m.pull_request, m.execution_id, m.workflow_id) for m in merges] == [
        (7, "a", "wf"),
        (9, "a", "wf"),
    ]


def _run_that_opens_pr_7(execution_id: str) -> list[DomainEvent]:
    """A run started on no PR whose one phase opened PR 7, through the real producers.

    The processor observes the phase's branches as it completes (with the PR
    the forge has open from each) and hands them to ``completed_phase``; the
    aggregate puts them on ``PhaseCompleted``. The observation names the
    workspace directory, ``widget``, as git does, not the slug.
    """
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf",
            workflow_name="implement",
            total_phases=1,
            inputs={"task": "build the widget"},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="Implement", order=1)],
            source_commits=[SourceCommit(repository=REPO, sha="a" * 40)],
        )
    )
    opened = BranchObservation(
        repo="widget",
        branch="feat/widget",
        remote="origin",
        remote_commit="b" * 40,
        remote_commit_at_phase_start=None,
        unpushed_commits=0,
        pull_request=7,
    )
    phase = completed_phase(
        execution_id=execution_id,
        workflow_id="wf",
        phase_id="implement",
        session_id="s",
        started_at=_at(0),
        artifact_ids=[],
        auth_tokens=None,
        now=_at(1),
        observed=ObservedBranches(branches=(opened,)),
    )
    aggregate.complete_phase(phase.command)
    aggregate.complete_execution(
        completed_execution([phase.result], []).as_command(execution_id, total_phases=1)
    )
    return [e.event for e in aggregate.get_uncommitted_events()]


async def _live(
    log: list[DomainEvent],
) -> tuple[ScorecardProjection, list[DomainEvent], tuple[int | None, Decimal | None]]:
    """Deliver ``log`` live, let the manager record, deliver what it recorded."""
    manager = MergedPullRequestAttributionProcessManager(
        store=InMemoryProjectionStore(), merges=_Forge(), recorder=_Recorder(log)
    )
    scorecard = ScorecardProjection(InMemoryProjectionStore())
    history = len(log)
    await _deliver((manager, scorecard), log)
    await manager.process_pending()
    recorded = log[history:]
    await _deliver((manager, scorecard), recorded)
    return scorecard, recorded, await _score(scorecard)


async def test_the_run_that_opened_a_pr_and_its_later_reverify_both_contribute() -> None:
    log = [*_run_that_opens_pr_7("a"), _started("c", 4, pr=7), _completed("c", 5)]
    assert not any(isinstance(e, WorkflowFailedEvent) for e in log)  # a succeeded

    scorecard, recorded, live = await _live(log)

    assert sorted(e.execution_id for e in recorded) == ["a", "c"]  # type: ignore[attr-defined]
    [merged] = await scorecard.merged_pull_requests_for_days(["2026-10-07"])
    assert (merged.repository, merged.pull_request) == (REPO, 7)
    assert sorted(merged.execution_ids) == ["a", "c"]
    assert live == (1, Decimal(5))  # the creator's 1 + the reverify's 4

    replay_recorder = _Recorder([])
    replayed = MergedPullRequestAttributionProcessManager(
        store=InMemoryProjectionStore(), merges=_Unreachable(), recorder=replay_recorder
    )
    rebuilt = ScorecardProjection(InMemoryProjectionStore())
    await _deliver((replayed, rebuilt), log)  # catch-up: handle_event only
    assert await _score(rebuilt) == live
    assert replay_recorder.log == []


async def test_the_run_that_opened_a_merged_pr_counts_it_on_its_own() -> None:
    _scorecard, recorded, live = await _live(_run_that_opens_pr_7("a"))

    assert [e.execution_id for e in recorded] == ["a"]  # type: ignore[attr-defined]
    assert live == (1, Decimal(1))
