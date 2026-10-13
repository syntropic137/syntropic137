"""A run's own to-do fold must say exactly what the shared projection says (ADR-072 D8).

THE EQUIVALENCE THESE TESTS GUARD. The run-scoped fold and the shared
`execution_todo` projection reach the same handlers by two different
dispatches: the fold through `project_events` (the journal's dispatch, keyed on
the event's own `event_type` and serialised from the event object), the shared
projection through the coordinator's `AutoDispatchProjection.handle_event`
(keyed on `envelope.metadata.event_type`). So the shared side here is driven
through `handle_event` with a real envelope, never through the journal - two
calls into the same dispatch would agree by construction and prove nothing.

At every step of each script three records are compared: the shared
projection's, a fold fed one event at a time as the journal feeds it, and a
fold rebuilt from scratch out of the stored prefix. The third is the restart
claim: discarding the fold loses nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import EventStoreExecutionEventStream
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    InheritedPhase,
    PhaseDefinition,
    ResumeOrigin,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
    ProvisionWorkspaceCompletedCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.AddExecutionTagsCommand import (
    AddExecutionTagsCommand,
)
from syn_domain.contexts.orchestration.domain.commands.RemoveExecutionTagsCommand import (
    RemoveExecutionTagsCommand,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
    ArtifactsCollectedForPhaseEvent,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseRetryScheduledEvent import (
    PhaseRetryScheduledEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
    PhaseStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.run_todo_fold import (
    ExecutionEventStream,
    RunScopedTodoFold,
    RunTodoStore,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
    TodoAction,
    TodoItem,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ExecutionRepository,
    )

WF = "wf-fold"
AT = datetime(2026, 10, 9, tzinfo=UTC)
NAME = ExecutionTodoProjection.PROJECTION_NAME


async def _fold(
    execution_id: str, repository: ExecutionRepository, events: ExecutionEventStream
) -> RunScopedTodoFold:
    """The fold as the composition root builds it: over the real projection class."""
    return await RunScopedTodoFold.for_execution(
        execution_id, repository, events, ExecutionTodoProjection
    )


def _started(execution_id: str, resumed_from: ResumeOrigin | None = None) -> DomainEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WF,
        execution_id=execution_id,
        workflow_name="fold",
        started_at=AT,
        total_phases=3,
        inputs={},
        phase_definitions=[
            {"phase_id": "review", "name": "review", "order": 2},
            {"phase_id": "implement", "name": "implement", "order": 1},
            {"phase_id": "fix", "name": "fix", "order": 3},
        ],
        resumed_from=resumed_from,
    )


def _phase(execution_id: str, phase_id: str, n: int) -> list[DomainEvent]:
    """One phase from provision to completion, with the noise a real stream carries."""
    return [
        PhaseStartedEvent(
            workflow_id=WF,
            execution_id=execution_id,
            phase_id=phase_id,
            phase_name=phase_id,
            phase_order=n,
            started_at=AT,
        ),
        WorkspaceProvisionedForPhaseEvent(
            workflow_id=WF,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=f"ws-{phase_id}-{n}",
            session_id=f"s-{phase_id}-{n}",
            provisioned_at=AT,
        ),
        AgentExecutionCompletedEvent(
            workflow_id=WF,
            execution_id=execution_id,
            phase_id=phase_id,
            session_id=f"s-{phase_id}-{n}",
            completed_at=AT,
        ),
        ArtifactsCollectedForPhaseEvent(
            workflow_id=WF,
            execution_id=execution_id,
            phase_id=phase_id,
            artifact_ids=[f"a-{phase_id}-{n}"],
            collected_at=AT,
        ),
    ]


def _next(execution_id: str, done: str, nxt: str, order: int) -> list[DomainEvent]:
    return [
        PhaseCompletedEvent(
            workflow_id=WF, execution_id=execution_id, phase_id=done, completed_at=AT, success=True
        ),
        NextPhaseReadyEvent(
            workflow_id=WF,
            execution_id=execution_id,
            completed_phase_id=done,
            next_phase_id=nxt,
            next_phase_order=order,
            decided_at=AT,
        ),
    ]


def _retry(execution_id: str, phase_id: str) -> DomainEvent:
    return PhaseRetryScheduledEvent(
        workflow_id=WF,
        execution_id=execution_id,
        phase_id=phase_id,
        attempt=2,
        reason="upstream busy",
        scheduled_at=AT,
    )


def _fresh_with_retry(execution_id: str) -> list[DomainEvent]:
    """implement (retried once) -> review -> fix -> done.

    Repair rounds are not hand-scripted: the aggregate refuses to restart a
    completed phase, so only its own commands can produce one. See
    `test_fold_matches_the_shared_projection_through_real_repair_rounds`.
    """
    implement = _phase(execution_id, "implement", 1)
    return [
        _started(execution_id),
        *implement[:3],
        _retry(execution_id, "implement"),
        *implement[1:],
        *_next(execution_id, "implement", "review", 2),
        *_phase(execution_id, "review", 2),
        *_next(execution_id, "review", "fix", 3),
        *_phase(execution_id, "fix", 3),
        PhaseCompletedEvent(
            workflow_id=WF,
            execution_id=execution_id,
            phase_id="fix",
            completed_at=AT,
            success=True,
        ),
        WorkflowCompletedEvent(
            workflow_id=WF,
            execution_id=execution_id,
            completed_at=AT,
            total_phases=3,
            completed_phases=3,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            total_duration_seconds=0.0,
            artifact_ids=[],
        ),
    ]


def _resume(execution_id: str) -> list[DomainEvent]:
    """A resume that inherits implement and starts at review."""
    origin = ResumeOrigin(
        parent_execution_id="exec-parent",
        inherited_phases=[InheritedPhase(phase_id="implement", artifact_ids=["a-parent"])],
        resume_phase_id="review",
    )
    return [
        _started(execution_id, resumed_from=origin),
        # A late event for the inherited phase must not put it back on the list.
        *_phase(execution_id, "implement", 1)[1:3],
        *_phase(execution_id, "review", 2),
        *_next(execution_id, "review", "fix", 3),
    ]


def _envelope(event: DomainEvent, execution_id: str, nonce: int) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_type=event.event_type,
            aggregate_id=execution_id,
            aggregate_type="WorkflowExecution",
            aggregate_nonce=nonce,
            global_nonce=nonce,
        ),
    )


@dataclass
class _StoredStream:
    """The `ExecutionEventStream` double: what the store holds for each execution."""

    streams: dict[str, list[DomainEvent]] = field(default_factory=dict)

    async def read(self, execution_id: str) -> Sequence[object]:
        return list(self.streams.get(execution_id, []))


class _UnusedRepository:
    """The seeding path must not touch the repository; any call here is a bug."""

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        raise AssertionError("seeding saved")

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        raise AssertionError("seeding saved")

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        raise AssertionError("seeding loaded the aggregate instead of reading its events")


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("execution_id", "script"),
    [
        ("exec-fold-fresh", _fresh_with_retry("exec-fold-fresh")),
        ("exec-fold-resume", _resume("exec-fold-resume")),
    ],
    ids=["fresh-retry", "resume"],
)
async def test_fold_matches_the_shared_projection_at_every_step(
    execution_id: str, script: list[DomainEvent]
) -> None:
    shared_store = InMemoryProjectionStore()
    shared = ExecutionTodoProjection(store=shared_store)
    checkpoints = MemoryCheckpointStore()
    stored = _StoredStream()
    live = await _fold(execution_id, _UnusedRepository(), stored)

    seen: list[list[TodoItem]] = []
    for nonce, event in enumerate(script, start=1):
        await shared.handle_event(_envelope(event, execution_id, nonce), checkpoints)
        await ExecutionJournal(_UnusedRepository(), live.projection)._project([event])  # pyright: ignore[reportPrivateUsage]
        stored.streams.setdefault(execution_id, []).append(event)
        rebuilt = await _fold(execution_id, _UnusedRepository(), stored)

        expected_record = await shared_store.get(NAME, execution_id)
        expected = await shared.get_pending(execution_id)
        step = f"step {nonce}: {event.event_type}"
        for fold in (live, rebuilt):
            assert await fold.projection.get_pending(execution_id) == expected, step
            assert await _record(fold) == expected_record, step
        seen.append(expected)

    # The scripts must actually exercise the paths they are named for, or the
    # equality above holds over nothing.
    flat = [item for todos in seen for item in todos]
    assert {item.action for item in flat} >= {
        TodoAction.PROVISION_WORKSPACE,
        TodoAction.RUN_AGENT,
        TodoAction.COLLECT_ARTIFACTS,
        TodoAction.COMPLETE_PHASE,
    }
    if execution_id.endswith("resume"):
        assert seen[0] == [
            TodoItem(
                execution_id=execution_id, action=TodoAction.PROVISION_WORKSPACE, phase_id="review"
            )
        ]
        assert all(item.phase_id != "implement" for item in flat)
    else:
        assert any(item.phase_id == "fix" for item in flat)
        assert seen[-1] == []


async def _record(fold: RunScopedTodoFold) -> object:
    records = await fold.projection._store.get_all(NAME)  # pyright: ignore[reportPrivateUsage]
    return records[0] if records else None


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_folds_journal_keeps_the_folds_own_projection_current() -> None:
    """The hop a run depends on: a save through `fold.journal` moves `fold.projection`."""
    execution_id = "exec-fold-journal"
    stored = _StoredStream({execution_id: [_started(execution_id)]})

    class _Saved:
        id = execution_id

        def __init__(self, events: list[DomainEvent]) -> None:
            self._events = events

        def get_uncommitted_events(self) -> list[EventEnvelope[DomainEvent]]:
            return [_envelope(e, execution_id, 0) for e in self._events]

    class _Repository(_UnusedRepository):
        async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
            return None

    fold = await _fold(execution_id, _Repository(), stored)
    assert [t.action for t in await fold.projection.get_pending(execution_id)] == [
        TodoAction.PROVISION_WORKSPACE
    ]

    provisioned = _phase(execution_id, "implement", 1)[1]
    await fold.journal.append(_Saved([provisioned]))  # type: ignore[arg-type]

    assert [t.action for t in await fold.projection.get_pending(execution_id)] == [
        TodoAction.RUN_AGENT
    ]


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_fold_reads_only_its_own_execution() -> None:
    """Two runs' folds never see each other, and neither writes the shared store."""
    stored = _StoredStream({"exec-a": [_started("exec-a")], "exec-b": [*_resume("exec-b")[:1]]})
    a = await _fold("exec-a", _UnusedRepository(), stored)
    b = await _fold("exec-b", _UnusedRepository(), stored)

    assert [t.phase_id for t in await a.projection.get_pending("exec-a")] == ["implement"]
    assert [t.phase_id for t in await b.projection.get_pending("exec-b")] == ["review"]
    with pytest.raises(ValueError, match="holds only its own"):
        await a.projection.get_pending("exec-b")


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_fold_constructs_and_folds_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-072 D8: a cache of durable events, so it must work where runs run.

    Construction is what is pinned, not the class hierarchy: an
    `assert_test_only()` call added to `RunTodoStore` would refuse production
    without changing its bases. The in-memory fitness check names this class
    too (`_NAMED_CANDIDATES`), so a guard added to it also fails that gate.
    """
    from syn_shared.settings import reset_settings

    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    reset_settings()
    try:
        from syn_shared.settings import get_settings

        assert not get_settings().uses_in_memory_stores
        execution_id = "exec-fold-production"
        fold = await _fold(
            execution_id,
            _UnusedRepository(),
            _StoredStream({execution_id: _fresh_with_retry(execution_id)[:3]}),
        )
        assert [t.action for t in await fold.projection.get_pending(execution_id)] == [
            TodoAction.RUN_AGENT
        ]
        assert not issubclass(RunTodoStore, InMemoryProjectionStore)
    finally:
        monkeypatch.delenv("APP_ENVIRONMENT")
        reset_settings()


@pytest.mark.unit
@pytest.mark.anyio
async def test_nothing_handed_in_or_out_of_the_store_reaches_its_record() -> None:
    """Only a save changes the fold: not mutating what was saved, nor what a read returned."""
    execution_id = "exec-fold-frozen"
    fold = await _fold(
        execution_id,
        _UnusedRepository(),
        _StoredStream({execution_id: _fresh_with_retry(execution_id)[:3]}),
    )
    store = fold.projection._store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
    assert isinstance(store, RunTodoStore)
    before = await fold.projection.get_pending(execution_id)
    snapshot = await store.get(NAME, execution_id)
    assert before and snapshot is not None

    for read in (
        await store.get(NAME, execution_id),
        (await store.get_all(NAME))[0],
        (await store.query(NAME))[0],
        (await store.get_by_prefix(NAME, "exec-"))[0][1],
    ):
        assert read is not None
        read["items"][0]["action"] = TodoAction.COMPLETE_EXECUTION.value
        read["items"].clear()
        read["phase_progress"].clear()
        read["execution_id"] = "exec-elsewhere"
    assert await fold.projection.get_pending(execution_id) == before
    assert await store.get(NAME, execution_id) == snapshot

    saved = await store.get(NAME, execution_id)
    assert saved is not None
    await store.save(NAME, execution_id, saved)
    saved["items"].clear()
    saved["phase_progress"]["implement"] = 99
    assert await fold.projection.get_pending(execution_id) == before
    assert await store.get(NAME, execution_id) == snapshot

    with pytest.raises(ValueError, match="expected"):
        await store.save(NAME, execution_id, {**snapshot, "unknown_field": 1})


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_event_store_reader_returns_the_execution_stream_in_order() -> None:
    """The adapter reads the stream the execution repository writes, and only that one."""
    from event_sourcing.client.memory import MemoryEventStoreClient

    client = MemoryEventStoreClient()
    script = _fresh_with_retry("exec-fold-store")[:5]
    await client.append_events(
        "WorkflowExecution-exec-fold-store",
        [_envelope(e, "exec-fold-store", i) for i, e in enumerate(script, start=1)],
    )
    await client.append_events(
        "WorkflowExecution-exec-other", [_envelope(_started("exec-other"), "exec-other", 1)]
    )

    events = await EventStoreExecutionEventStream(client).read("exec-fold-store")

    assert [e.event_type for e in events] == [e.event_type for e in script]
    fold = await _fold(
        "exec-fold-store", _UnusedRepository(), EventStoreExecutionEventStream(client)
    )
    assert [t.action for t in await fold.projection.get_pending("exec-fold-store")] == [
        TodoAction.PROVISION_WORKSPACE
    ]


#: The shape of workflows/sdlc/implement-v3, as the aggregate's own round tests use it.
_ROUND_PHASES = ("implement", "verify", "fix", "reverify", "fix_2", "reverify_2", "finalize_pr")


def _repair_rounds(execution_id: str) -> list[DomainEvent]:
    """A blocked verify, one fix, a certified reverify: every event from real commands.

    The aggregate decides each next phase from the verdicts, so the certified
    reverify skips `fix_2`/`reverify_2` and the run goes on to `finalize_pr`.
    """
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=WF,
            workflow_name="rounds",
            total_phases=len(_ROUND_PHASES),
            inputs={},
            phase_definitions=[
                PhaseDefinition(phase_id=p, name=p, order=i + 1)
                for i, p in enumerate(_ROUND_PHASES)
            ],
        )
    )
    verdicts = {"verify": "blocked", "reverify": "certified"}
    phase_id: str | None = _ROUND_PHASES[0]
    while phase_id is not None:
        aggregate.start_phase(
            StartPhaseCommand(
                execution_id=execution_id,
                workflow_id=WF,
                phase_id=phase_id,
                phase_name=phase_id,
                phase_order=_ROUND_PHASES.index(phase_id) + 1,
            )
        )
        aggregate.provision_workspace_completed(
            ProvisionWorkspaceCompletedCommand(
                execution_id=execution_id,
                phase_id=phase_id,
                workspace_id=f"ws-{phase_id}",
                session_id=f"s-{phase_id}",
            )
        )
        aggregate.agent_execution_completed(
            AgentExecutionCompletedCommand(
                execution_id=execution_id,
                phase_id=phase_id,
                session_id=f"s-{phase_id}",
                reported_review_verdict=ReviewVerdict.from_reported(verdicts.get(phase_id)),
            )
        )
        decided = len(aggregate.get_uncommitted_events())
        aggregate.artifacts_collected(
            ArtifactsCollectedCommand(execution_id=execution_id, phase_id=phase_id, artifact_ids=[])
        )
        aggregate.complete_phase(
            CompletePhaseCommand(
                execution_id=execution_id,
                workflow_id=WF,
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
        nexts = [
            e.event
            for e in aggregate.get_uncommitted_events()[decided:]
            if isinstance(e.event, NextPhaseReadyEvent)
        ]
        phase_id = nexts[0].next_phase_id if nexts else None
    return [envelope.event for envelope in aggregate.get_uncommitted_events()]


@pytest.mark.unit
@pytest.mark.anyio
async def test_fold_matches_the_shared_projection_through_real_repair_rounds() -> None:
    execution_id = "exec-fold-rounds"
    script = _repair_rounds(execution_id)
    shared_store = InMemoryProjectionStore()
    shared = ExecutionTodoProjection(store=shared_store)
    checkpoints = MemoryCheckpointStore()

    served: list[tuple[str | None, TodoAction]] = []
    for nonce, event in enumerate(script, start=1):
        await shared.handle_event(_envelope(event, execution_id, nonce), checkpoints)
        rebuilt = await _fold(
            execution_id, _UnusedRepository(), _StoredStream({execution_id: script[:nonce]})
        )
        step = f"step {nonce}: {event.event_type}"
        expected = await shared.get_pending(execution_id)
        assert await rebuilt.projection.get_pending(execution_id) == expected, step
        assert await _record(rebuilt) == await shared_store.get(NAME, execution_id), step
        served += [(t.phase_id, t.action) for t in expected if (t.phase_id, t.action) not in served]

    # The repair phases themselves walk the whole lifecycle; the skipped round never appears.
    lifecycle = [
        TodoAction.PROVISION_WORKSPACE,
        TodoAction.RUN_AGENT,
        TodoAction.COLLECT_ARTIFACTS,
        TodoAction.COMPLETE_PHASE,
    ]
    for phase in ("fix", "reverify", "finalize_pr"):
        assert [a for p, a in served if p == phase] == lifecycle, phase
    assert not [p for p, _ in served if p in ("fix_2", "reverify_2")]
    assert any(getattr(e, "skipped_phase_ids", None) for e in script)


class _PagedClient:
    """The production gRPC client's read contract: one call is one page.

    `read_events(stream, from_version)` returns at most `page` events whose
    nonce is >= `from_version` (the server's inclusive cursor, `max_count`
    1,000 in the real client), in nonce order.
    """

    def __init__(self, envelopes: list[EventEnvelope[DomainEvent]], page: int) -> None:
        self._envelopes = envelopes
        self._page = page
        self.calls = 0

    async def read_events(
        self, stream_name: str, from_version: int | None = None
    ) -> list[EventEnvelope[DomainEvent]]:
        self.calls += 1
        start = max(from_version or 0, 1)
        return [e for e in self._envelopes if e.metadata.aggregate_nonce >= start][: self._page]


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("tag_pairs", [499, 1249], ids=["1001-events", "2501-events"])
async def test_the_event_store_reader_reads_past_one_page(tag_pairs: int) -> None:
    """The decisive event sits after the last page boundary; missing it changes the action."""
    execution_id = "exec-fold-long"
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=WF,
            workflow_name="long",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="implement", order=1)],
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id=WF,
            phase_id="implement",
            phase_name="implement",
            phase_order=1,
        )
    )
    for _ in range(tag_pairs):
        aggregate.add_tags(AddExecutionTagsCommand(aggregate_id=execution_id, tags=["t"]))
        aggregate.remove_tags(RemoveExecutionTagsCommand(aggregate_id=execution_id, tags=["t"]))
    aggregate.provision_workspace_completed(
        ProvisionWorkspaceCompletedCommand(
            execution_id=execution_id, phase_id="implement", workspace_id="ws", session_id="s"
        )
    )
    envelopes = list(aggregate.get_uncommitted_events())
    assert len(envelopes) == 2 * tag_pairs + 3
    client = _PagedClient(envelopes, page=1000)
    reader = EventStoreExecutionEventStream(client)  # type: ignore[arg-type]

    events = await reader.read(execution_id)

    assert [e.metadata.aggregate_nonce for e in envelopes] == list(range(1, len(envelopes) + 1))
    assert events == [e.event for e in envelopes]
    assert client.calls > 2
    fold = await _fold(execution_id, _UnusedRepository(), reader)
    assert [t.action for t in await fold.projection.get_pending(execution_id)] == [
        TodoAction.RUN_AGENT
    ]
