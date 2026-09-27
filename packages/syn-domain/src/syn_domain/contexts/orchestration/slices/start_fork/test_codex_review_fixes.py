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
class _Store:
    rows: dict[str, dict[str, object]] = field(default_factory=dict)

    async def save(self, projection: str, key: str, row: dict[str, object]) -> None:
        del projection
        self.rows[key] = row

    async def query(self, projection: str, filters: dict[str, str]) -> list[dict[str, object]]:
        del projection
        return [r for r in self.rows.values() if r.get("status") == filters.get("status")]

    async def delete_all(self, projection: str) -> None:
        del projection
        self.rows.clear()


@dataclass
class _Starter:
    raising: Exception

    async def start_fork(self, parent_execution_id: str) -> None:
        del parent_execution_id
        raise self.raising


async def _run_start(record: ForkStartRecord, *, raising: Exception) -> ForkStartRecord:
    """One `_start` against a starter that raises, returning what was stored."""
    store = _Store()
    manager = ForkStartProcessManager(fork_starter=_Starter(raising), store=store)
    await manager._start(record)
    return ForkStartRecord.model_validate(store.rows[PARENT])
