"""Two fail-open paths the codex review of #1459 found (ADR-014 s7).

Both were found by review, not by CI, and both concern a fork that STARTS when
it should not have: one running without the outputs it inherited, one thrown
away because a store blinked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, ProjectionResult

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.artifacts import PhaseOutputFile
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartForkCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    ForkOrigin,
    InheritedPhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.fork_handoff import (
    InheritanceUnavailableError,
    inherited_outputs,
)
from syn_domain.contexts.orchestration.slices.start_fork.ForkStartProcessManager import (
    ForkStartProcessManager,
)
from syn_domain.contexts.orchestration.slices.start_fork.StartForkHandler import (
    StartForkHandler,
)
from syn_domain.contexts.orchestration.slices.start_fork.value_objects import (
    DISPATCH_GRACE,
    MAX_START_ATTEMPTS,
    ForkStartRecord,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.orchestration.slices.start_fork.ForkStartProcessManager import (
        StartFailureReporter,
    )

pytestmark = pytest.mark.unit

PARENT = "exec-parent"


def _origin(*, artifacts: list[str]) -> ForkOrigin:
    return ForkOrigin(
        parent_execution_id=PARENT,
        inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=artifacts)],
        resume_phase_id="plan",
    )


@dataclass
class _Query:
    """Returns exactly what it is told to, so a MISS can be expressed."""

    answer: dict[str, list[PhaseOutputFile]] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    async def get_files_for_artifacts(
        self, execution_id: str, phase_artifact_ids: Mapping[str, Sequence[str]]
    ) -> dict[str, list[PhaseOutputFile]]:
        del phase_artifact_ids
        self.asked.append(execution_id)
        return self.answer


class TestAForkWillNotStartWithoutItsInheritance:
    """Finding 2. The resumed phase reads its predecessors' files.

    Returning a short cache meant the child ran the wrong work at full price and
    reported success. `inherited_outputs` is called before `_journal.open`, so
    raising here means no child stream exists to be stranded.
    """

    async def test_a_recorded_artifact_that_resolves_to_nothing_refuses_the_start(self) -> None:
        with pytest.raises(
            InheritanceUnavailableError, match="holds no files for the artifact ids"
        ):
            await inherited_outputs(_Query(answer={}), _origin(artifacts=["art-research"]))

    async def test_no_query_service_refuses_when_there_was_something_to_read(self) -> None:
        with pytest.raises(InheritanceUnavailableError, match="no artifact query service"):
            await inherited_outputs(None, _origin(artifacts=["art-research"]))

    async def test_a_phase_that_produced_nothing_is_not_a_miss(self) -> None:
        """Nothing recorded means nothing missing - this must still start."""
        cache = await inherited_outputs(_Query(answer={}), _origin(artifacts=[]))
        assert cache.primary == {}
        assert cache.files == {}

    async def test_a_resolved_inheritance_is_handed_over(self) -> None:
        query = _Query(
            answer={"research": [PhaseOutputFile(source_path=None, content="the parent's work")]}
        )
        cache = await inherited_outputs(query, _origin(artifacts=["art-research"]))
        assert cache.primary["research"] == "the parent's work"
        assert [f.content for f in cache.files["research"]] == ["the parent's work"]


class TestAnInfrastructureBlipDoesNotDiscardAnAdmittedFork:
    """Finding 3. `except Exception -> failed` threw away admitted forks.

    A store that is down says nothing about whether a fork MAY start. The
    distinction is carried by the exception TYPE, never by matching its prose.
    """

    @staticmethod
    def _record(attempts: int = 0) -> ForkStartRecord:
        return ForkStartRecord(
            parent_execution_id=PARENT, recorded_at=datetime.now(UTC), attempts=attempts
        )

    def test_retryable_is_owed_and_failed_is_not(self) -> None:
        from syn_domain.contexts.orchestration.slices.start_fork.value_objects import (
            OWED_STATUSES,
        )

        assert "retryable" in OWED_STATUSES
        assert "failed" not in OWED_STATUSES

    def test_the_ceiling_exists_so_a_permanent_fault_still_settles(self) -> None:
        assert MAX_START_ATTEMPTS >= 1

    async def test_a_domain_refusal_is_terminal_at_once(self) -> None:
        saved = await _run_start(self._record(), raising=ValueError("it was cancelled"))
        assert saved.status == "failed"
        assert saved.attempts == 0, "a refusal is not a spent attempt"

    async def test_a_store_outage_stays_owed(self) -> None:
        saved = await _run_start(self._record(), raising=ConnectionError("store down"))
        assert saved.status == "retryable"
        assert saved.attempts == 1

    async def test_it_settles_once_the_attempts_are_spent(self) -> None:
        saved = await _run_start(
            self._record(attempts=MAX_START_ATTEMPTS - 1), raising=ConnectionError("still down")
        )
        assert saved.status == "failed"
        assert saved.attempts == MAX_START_ATTEMPTS


@dataclass
class _Starter:
    raising: Exception

    async def start_fork(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> None:
        del parent_execution_id, on_failure
        raise self.raising


async def _offer(manager: ForkStartProcessManager, record: ForkStartRecord) -> bool:
    """`_start` as `process_pending` calls it: on a record the store holds.

    A pass only ever offers what it read, and `_start` dispatches only over
    exactly that record, so a record must be stored before it can be offered.
    """
    await manager._save(record)
    return await manager._start(record)


async def _stored(store: InMemoryProjectionStore) -> ForkStartRecord:
    row = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
    assert row is not None, "nothing was recorded"
    return ForkStartRecord.model_validate(row)


async def _run_start(record: ForkStartRecord, *, raising: Exception) -> ForkStartRecord:
    """One `_start` against a starter that raises, returning what was stored."""
    store = InMemoryProjectionStore()
    manager = ForkStartProcessManager(fork_starter=_Starter(raising), store=store)
    await _offer(manager, record)
    stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
    assert stored is not None, "the attempt recorded nothing"
    return ForkStartRecord.model_validate(stored)


class TestADispatchIsNotAStart:
    """Finding 1. The crash window between spawning a start and a child existing.

    `ForkStarter.start_fork` hands the work to a background task and returns, so
    marking the record `started` at that point recorded a child that might never
    be written. A process death in between left the parent having admitted a
    fork, no child stream, and nothing owed - the fork was simply lost.

    Re-offering is safe, which is what makes "stay owed" the right answer rather
    than a bespoke recovery path: the child's id is fixed by the parent's
    `ExecutionForked`, and `StartForkHandler.handle` returns early when that
    child already exists.
    """

    @staticmethod
    def _record(status: str = "pending") -> ForkStartRecord:
        return ForkStartRecord(
            parent_execution_id=PARENT,
            recorded_at=datetime.now(UTC),
            status=status,  # pyright: ignore[reportArgumentType]
        )

    def test_dispatched_is_still_owed(self) -> None:
        from syn_domain.contexts.orchestration.slices.start_fork.value_objects import (
            OWED_STATUSES,
        )

        assert "dispatched" in OWED_STATUSES, (
            "a dispatch that has not produced a child must be re-offered"
        )

    async def test_a_successful_dispatch_records_dispatched_not_started(self) -> None:
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        assert await _offer(manager, self._record()) is True

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "dispatched"

    async def test_the_childs_own_start_event_settles_it(self) -> None:
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await _offer(manager, self._record())

        await manager._settle_if_a_fork_started(_ChildStarted(PARENT))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "started"

    async def test_an_ordinary_execution_starting_settles_nothing(self) -> None:
        """A run that is not a fork carries no `forked_from` and owes nothing."""
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await _offer(manager, self._record())

        await manager._settle_if_a_fork_started(_ChildStarted(None))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "dispatched"


class TestALateReportFromTheTask:
    """#1463's report arrives from a task that runs the WHOLE child.

    So it can land after the child's start event settled the record, or after a
    later dispatch replaced it. Either way it speaks for nothing current, and
    `_save` would let `failed` replace `started` - erasing a start that happened.
    """

    @staticmethod
    def _record() -> ForkStartRecord:
        return ForkStartRecord(parent_execution_id=PARENT, recorded_at=datetime.now(UTC))

    async def test_it_does_not_unsettle_a_child_that_started(self) -> None:
        store = InMemoryProjectionStore()
        starter = _Reporting()
        manager = ForkStartProcessManager(fork_starter=starter, store=store)
        await _offer(manager, self._record())
        await manager._settle_if_a_fork_started(_ChildStarted(PARENT))

        assert starter.on_failure is not None
        await starter.on_failure(ValueError("the child's second phase was refused"))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "started"

    async def test_it_does_not_speak_for_a_later_dispatch(self) -> None:
        store = InMemoryProjectionStore()
        first, second = _Reporting(), _Reporting()
        await _offer(ForkStartProcessManager(fork_starter=first, store=store), self._record())
        # The later pass offers what IT reads: the first dispatch, past its grace.
        await ForkStartProcessManager(fork_starter=second, store=store)._start(await _stored(store))

        assert first.on_failure is not None
        await first.on_failure(ConnectionError("from the first task"))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        saved = ForkStartRecord.model_validate(stored)
        assert (saved.status, saved.attempts) == ("dispatched", 0)

    async def test_a_current_report_is_recorded(self) -> None:
        store = InMemoryProjectionStore()
        starter = _Reporting()
        manager = ForkStartProcessManager(fork_starter=starter, store=store)
        await _offer(manager, self._record())

        assert starter.on_failure is not None
        await starter.on_failure(ConnectionError("store down"))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        saved = ForkStartRecord.model_validate(stored)
        assert (saved.status, saved.attempts, saved.status_reason) == (
            "retryable",
            1,
            "store down",
        )

    @pytest.mark.parametrize(
        ("attempts", "failure"),
        [
            (0, ValueError("the child's second phase was refused")),
            (MAX_START_ATTEMPTS - 1, ConnectionError("the last attempt's store was down")),
        ],
        ids=["refused", "attempts-spent"],
    )
    async def test_a_start_that_lands_between_its_read_and_its_write_survives(
        self, monkeypatch: pytest.MonkeyPatch, attempts: int, failure: Exception
    ) -> None:
        """The interleaving the verification of #1466 reproduced.

        The report reads the record, finds THIS dispatch, and writes `failed` -
        two store operations. The child's start event settled `started` in
        between, and the write erased it; an existing child emits no second
        start, so nothing ever put it back. The settle is forced into exactly
        that gap: after the report's read of `dispatched`, before its write.
        Both ways a report concludes `failed` are driven, since `failed` is the
        only status that could replace `started`.
        """
        store = InMemoryProjectionStore()
        starter = _Reporting()
        manager = ForkStartProcessManager(fork_starter=starter, store=store)
        await _offer(manager, self._record().model_copy(update={"attempts": attempts}))

        read = store.get
        settles: list[asyncio.Task[ProjectionResult]] = []

        async def settle_after_the_report_reads(projection: str, key: str):
            row = await read(projection, key)
            if not settles and row is not None and row.get("status") == "dispatched":
                settles.append(
                    asyncio.create_task(
                        manager.handle_event(
                            _envelope("WorkflowExecutionStarted", _real_child_start(PARENT)),
                            _Checkpoints(),
                        )
                    )
                )
                # Let the settle run to completion if nothing holds it back. A
                # transition that is atomic holds it until this read's write.
                await asyncio.wait(settles, timeout=0.2)
            return row

        monkeypatch.setattr(store, "get", settle_after_the_report_reads)

        assert starter.on_failure is not None
        await starter.on_failure(failure)
        assert settles, "the interleaving was never reached, so nothing was tested"
        assert await settles[0] is ProjectionResult.SUCCESS

        assert await _status(store) == "started"


@dataclass
class _Reporting:
    """A starter that spawns, keeping the reporter its task would call."""

    on_failure: StartFailureReporter | None = None

    async def start_fork(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> None:
        del parent_execution_id
        self.on_failure = on_failure


class _Spawning:
    """A starter that returns without producing a child, as the real one does."""

    async def start_fork(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> None:
        del parent_execution_id, on_failure


@dataclass
class _Origin:
    parent_execution_id: str


@dataclass
class _ChildStarted:
    """A `WorkflowExecutionStarted` as the process manager reads it."""

    parent: str | None

    @property
    def forked_from(self) -> _Origin | None:
        return None if self.parent is None else _Origin(self.parent)


class TestTheEventActuallyReachesTheSettle:
    """The wiring, not just the method.

    Written because a mutation proved it was missing: replacing the
    `handle_event` dispatch with `pass` killed NO test, since every test above
    calls `_settle_if_a_fork_started` directly. A method that works and is never
    reached is the same as a method that does not work.
    """

    async def test_a_childs_start_envelope_settles_the_record(self) -> None:
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await _offer(
            manager, ForkStartRecord(parent_execution_id=PARENT, recorded_at=datetime.now(UTC))
        )

        result = await manager.handle_event(
            _envelope("WorkflowExecutionStarted", _real_child_start(PARENT)),
            _Checkpoints(),
        )

        assert result is ProjectionResult.SUCCESS
        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "started", (
            "the child's start event did not reach the settle"
        )

    async def test_the_started_event_type_is_subscribed(self) -> None:
        """Handling it is moot if the coordinator never delivers it."""
        subscribed = ForkStartProcessManager().get_subscribed_event_types()
        assert subscribed is not None
        assert "WorkflowExecutionStarted" in subscribed


class _Checkpoints:
    """Accepts a checkpoint and remembers nothing; the record is the assertion."""

    async def save_checkpoint(self, checkpoint: object) -> None:
        del checkpoint

    async def get_checkpoint(self, projection_name: str) -> None:
        del projection_name

    async def delete_checkpoint(self, projection_name: str) -> None:
        del projection_name


def _real_child_start(parent: str) -> WorkflowExecutionStartedEvent:
    """The child's ACTUAL start event, not a stand-in.

    The envelope validates its event as a `DomainEvent`, and using the real one
    also pins that `forked_from` is where the parent's id genuinely lives.
    """
    return WorkflowExecutionStartedEvent(
        workflow_id="wf-1",
        execution_id="exec-child",
        workflow_name="Forked",
        started_at=datetime.now(UTC),
        total_phases=3,
        inputs={},
        forked_from=ForkOrigin(
            parent_execution_id=parent,
            inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["a1"])],
            resume_phase_id="plan",
        ),
    )


def _envelope(event_type: str, event: DomainEvent) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="exec-child",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            event_type=event_type,
            global_nonce=1,
        ),
    )


class TestTheSequencesTheSecondReviewNamed:
    """Round two of the #1459 review rejected round one's fixes. These are its
    three sequences, each of which passed the previous tests."""

    @staticmethod
    def _pending() -> ForkStartRecord:
        return ForkStartRecord(parent_execution_id=PARENT, recorded_at=datetime.now(UTC))

    async def test_a_settle_that_lands_first_is_not_overwritten(self) -> None:
        """The race: `_start` used to save `dispatched` AFTER spawning.

        The child could open its stream and its start event settle `started`
        while that save was still in flight; the save then overwrote it, and
        nothing settled it again because an existing child emits no second start
        event. Here the settle is forced to land first and must survive.
        """
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._save(self._pending())

        # The child's event arrives before anything writes `dispatched`.
        await manager._settle_if_a_fork_started(_real_child_start(PARENT))
        # A late dispatch write must not walk it back.
        await manager._save(
            self._pending().model_copy(
                update={"status": "dispatched", "dispatched_at": datetime.now(UTC)}
            )
        )

        assert await _status(store) == "started"

    async def test_a_failed_record_is_not_walked_back_either(self) -> None:
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._save(
            self._pending().model_copy(update={"status": "failed", "status_reason": "refused"})
        )

        await manager._save(self._pending().model_copy(update={"status": "retryable"}))

        assert await _status(store) == "failed"

    async def test_no_conclusion_replaces_a_start(self) -> None:
        """`started` is a fact about the child's stream, `failed` a judgment.

        A failure reported by ANY path - including one with no dispatch to
        compare against - must not erase a child that exists, since that child
        emits no second start event to put the record back.
        """
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._save(self._pending().model_copy(update={"status": "started"}))

        await manager._save(
            self._pending().model_copy(update={"status": "failed", "status_reason": "late"})
        )

        assert await _status(store) == "started"

    async def test_the_child_starting_still_settles_a_failed_record(self) -> None:
        """The converse: a start that happened anyway is the truth."""
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._save(
            self._pending().model_copy(update={"status": "failed", "status_reason": "refused"})
        )

        await manager._settle_if_a_fork_started(_real_child_start(PARENT))

        assert await _status(store) == "started"

    async def test_a_dispatch_in_flight_is_not_re_offered_within_the_grace(self) -> None:
        """Each re-offer takes an admission ticket and a task that waits for a
        semaphore slot before finding the child - so a slow start must not be
        dispatched on every pass."""
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._save(
            self._pending().model_copy(
                update={"status": "dispatched", "dispatched_at": datetime.now(UTC)}
            )
        )

        assert await manager.process_pending() == 0, "an in-flight start was dispatched again"

    async def test_a_dispatch_stuck_past_the_grace_is_re_offered(self) -> None:
        """The other half: the grace must not become a way to lose a fork."""
        store = InMemoryProjectionStore()
        starter = _Spawning()
        manager = ForkStartProcessManager(fork_starter=starter, store=store)
        await manager._save(
            self._pending().model_copy(
                update={
                    "status": "dispatched",
                    "dispatched_at": datetime.now(UTC) - DISPATCH_GRACE - timedelta(seconds=1),
                }
            )
        )

        assert await manager.process_pending() == 1

    async def test_the_other_owed_statuses_are_due_at_once(self) -> None:
        """Nothing is running for pending, paused or retryable, so none waits."""
        for status in ("pending", "paused", "retryable"):
            store = InMemoryProjectionStore()
            manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
            await manager._save(self._pending().model_copy(update={"status": status}))
            assert await manager.process_pending() == 1, f"{status} was not offered"


async def _status(store: InMemoryProjectionStore) -> str:
    row = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
    assert row is not None
    return ForkStartRecord.model_validate(row).status


class TestValidateResolvesTheInheritanceBeforeDispatch:
    """Where the refusal has to happen, proved by driving `validate` itself.

    A mutation exposed this as untested: replacing the `inherited_outputs` call
    in `StartForkHandler.validate` with `pass` killed nothing, because every
    inheritance test called `inherited_outputs` directly. The point of the change
    is WHERE it is called - synchronously, before the dispatcher spawns anything -
    so the test has to go through `validate`.
    """

    async def test_a_vanished_artifact_is_refused_synchronously(self) -> None:
        handler = StartForkHandler(
            _Processor(query=_Query(answer={})),  # pyright: ignore[reportArgumentType]
            _Executions(),  # pyright: ignore[reportArgumentType]
        )

        with pytest.raises(
            InheritanceUnavailableError, match="holds no files for the artifact ids"
        ):
            await handler.validate(PARENT)

    async def test_a_resolvable_inheritance_passes_validate(self) -> None:
        query = _Query(
            answer={"research": [PhaseOutputFile(source_path=None, content="the parent's work")]}
        )
        handler = StartForkHandler(
            _Processor(query=query),  # pyright: ignore[reportArgumentType]
            _Executions(),  # pyright: ignore[reportArgumentType]
        )

        await handler.validate(PARENT)
        assert query.asked, "validate did not consult the artifact query at all"


@dataclass
class _Processor:
    """Stands in for the processor, for the one thing validate asks of it."""

    query: _Query

    async def resolve_inheritance(self, origin: object) -> None:
        await inherited_outputs(self.query, origin)  # pyright: ignore[reportArgumentType]


class _Executions:
    """A parent that admitted a fork of one inherited phase with one artifact."""

    async def get_by_id(self, aggregate_id: str) -> _Parent:
        del aggregate_id
        return _Parent()


def _phase(phase_id: str, order: int) -> ExecutablePhase:
    """A pinned phase, so `refuse_fork_start` passes and the inheritance check
    is what the test actually reaches."""
    return ExecutablePhase(
        phase_id=phase_id,
        name=phase_id.title(),
        order=order,
        agent_config=AgentConfiguration(),
        prompt_template=f"{phase_id} as pinned",
        output_artifact_types=(),
        timeout_seconds=1800,
    )


class _Parent:
    def fork_start_command(self) -> StartForkCommand:
        return StartForkCommand(
            execution_id="exec-child",
            workflow_id="wf-1",
            workflow_name="Forked",
            inputs={},
            pinned_phases=[
                _phase("research", 1),
                _phase("plan", 2),
            ],
            source_commits=[],
            forked_from=ForkOrigin(
                parent_execution_id=PARENT,
                inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["a1"])],
                resume_phase_id="plan",
            ),
        )


class TestTwoPassesOfferingTheSameRecord:
    """The codex review of #1466: concurrent dispatches erased attempt history.

    Two `process_pending` passes can both read the same owed record before
    either writes. Each then wrote `dispatched` and spawned a start, and the
    loser's write - of the record as it was BEFORE the winner's attempt - landed
    over whatever the winner's attempt had since recorded. A `retryable` with
    its attempt counted went back to `dispatched` with none, so the ceiling on
    attempts could be walked back without limit.
    """

    @staticmethod
    def _pending() -> ForkStartRecord:
        return ForkStartRecord(parent_execution_id=PARENT, recorded_at=datetime.now(UTC))

    async def test_the_stale_dispatch_neither_lands_nor_starts(self) -> None:
        store = InMemoryProjectionStore()
        starter = _ReportingAll()
        manager = ForkStartProcessManager(fork_starter=starter, store=store)
        await manager._save(self._pending())

        # read, read - both passes see the same pending record
        [first_read] = await manager._owed_records()
        [second_read] = await manager._owed_records()
        # save - the first dispatches, and its start fails and is counted
        assert await manager._start(first_read) is True
        await starter.reports[0](ConnectionError("store blipped"))
        # save - the second writes from what it read before all that
        dispatched_again = await manager._start(second_read)

        saved = await _stored(store)
        assert (saved.status, saved.attempts, saved.status_reason) == (
            "retryable",
            1,
            "store blipped",
        )
        assert dispatched_again is False
        assert len(starter.reports) == 1, "the stale pass started a second child"

    async def test_a_synchronous_failure_does_not_speak_for_a_later_dispatch(self) -> None:
        """The other unfenced write: `start_fork` raising, after the record moved on.

        While this attempt's `start_fork` was failing, a later pass dispatched
        again. The failure belongs to the attempt that was replaced, and
        recording it would put back an attempt count and reason the later
        dispatch had already cleared.
        """
        store = InMemoryProjectionStore()
        later = ForkStartProcessManager(fork_starter=_Spawning(), store=store)

        class _RaisingAfterALaterDispatch:
            async def start_fork(
                self, parent_execution_id: str, *, on_failure: StartFailureReporter
            ) -> None:
                del parent_execution_id, on_failure
                assert await later._start(await _stored(store)) is True
                raise ConnectionError("from the replaced attempt")

        manager = ForkStartProcessManager(fork_starter=_RaisingAfterALaterDispatch(), store=store)
        assert await _offer(manager, self._pending()) is False
        redispatched = await _stored(store)

        assert (redispatched.status, redispatched.attempts, redispatched.status_reason) == (
            "dispatched",
            0,
            None,
        )

    async def test_the_pass_that_read_the_current_record_still_dispatches(self) -> None:
        """The converse, so the fence is not simply "never dispatch twice"."""
        store = InMemoryProjectionStore()
        starter = _ReportingAll()
        manager = ForkStartProcessManager(fork_starter=starter, store=store)
        await manager._save(self._pending())

        [first_read] = await manager._owed_records()
        assert await manager._start(first_read) is True
        await starter.reports[0](ConnectionError("store blipped"))
        [retry] = await manager._owed_records()
        assert await manager._start(retry) is True

        saved = await _stored(store)
        assert (saved.status, saved.attempts) == ("dispatched", 1)
        assert len(starter.reports) == 2


@dataclass
class _ReportingAll:
    """A starter that spawns, keeping every reporter it was handed, in order."""

    reports: list[StartFailureReporter] = field(default_factory=list)

    async def start_fork(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> None:
        del parent_execution_id
        self.reports.append(on_failure)
