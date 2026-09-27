"""Two fail-open paths the codex review of #1459 found (ADR-014 s7).

Both were found by review, not by CI, and both concern a fork that STARTS when
it should not have: one running without the outputs it inherited, one thrown
away because a store blinked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.artifacts import PhaseOutputFile
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    ForkOrigin,
    InheritedPhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.fork_handoff import (
    InheritanceUnavailableError,
    inherited_outputs,
)
from syn_domain.contexts.orchestration.slices.start_fork.ForkStartProcessManager import (
    ForkStartProcessManager,
)
from syn_domain.contexts.orchestration.slices.start_fork.value_objects import (
    MAX_START_ATTEMPTS,
    ForkStartRecord,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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

    async def get_files_for_artifacts(
        self, execution_id: str, phase_artifact_ids: Mapping[str, Sequence[str]]
    ) -> dict[str, list[PhaseOutputFile]]:
        del execution_id, phase_artifact_ids
        return self.answer


class TestAForkWillNotStartWithoutItsInheritance:
    """Finding 2. The resumed phase reads its predecessors' files.

    Returning a short cache meant the child ran the wrong work at full price and
    reported success. `inherited_outputs` is called before `_journal.open`, so
    raising here means no child stream exists to be stranded.
    """

    async def test_a_recorded_artifact_that_resolves_to_nothing_refuses_the_start(self) -> None:
        with pytest.raises(InheritanceUnavailableError, match="resolved to no files"):
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

    async def start_fork(self, parent_execution_id: str) -> None:
        del parent_execution_id
        raise self.raising


async def _run_start(record: ForkStartRecord, *, raising: Exception) -> ForkStartRecord:
    """One `_start` against a starter that raises, returning what was stored."""
    store = InMemoryProjectionStore()
    manager = ForkStartProcessManager(fork_starter=_Starter(raising), store=store)
    await manager._start(record)
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
        assert await manager._start(self._record()) is True

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "dispatched"

    async def test_the_childs_own_start_event_settles_it(self) -> None:
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._start(self._record())

        await manager._settle_if_a_fork_started(_ChildStarted(PARENT))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "started"

    async def test_an_ordinary_execution_starting_settles_nothing(self) -> None:
        """A run that is not a fork carries no `forked_from` and owes nothing."""
        store = InMemoryProjectionStore()
        manager = ForkStartProcessManager(fork_starter=_Spawning(), store=store)
        await manager._start(self._record())

        await manager._settle_if_a_fork_started(_ChildStarted(None))

        stored = await store.get(ForkStartProcessManager.PROJECTION_NAME, PARENT)
        assert stored is not None
        assert ForkStartRecord.model_validate(stored).status == "dispatched"


class _Spawning:
    """A starter that returns without producing a child, as the real one does."""

    async def start_fork(self, parent_execution_id: str) -> None:
        del parent_execution_id


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
