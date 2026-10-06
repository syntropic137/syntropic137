"""Eval read models, rebuilt by replay (evals plan step 5, #967).

The fixture stream is written by the real aggregates through real
repositories, read back off the store in global order and dispatched through
``handle_event``, the entry point the coordinator uses: create an Eval, freeze
it, put two runs in it (one launched, one attached), attach and then detach a
third, fail one member, archive the Eval. Every assertion is on fresh
projections, replayed twice, so a handler that appends instead of overwrites
shows up as an inflated count.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import TYPE_CHECKING

os.environ.setdefault("APP_ENVIRONMENT", "test")

from unittest.mock import patch

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration._shared.execution_list_reads import WORKFLOW_EXECUTIONS
from syn_domain.contexts.orchestration._shared.repository_baseline import RepositoryBaseline
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ArchiveEvalCommand import (
    ArchiveEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.AttachExecutionToEvalCommand import (
    AttachExecutionToEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.CreateEvalCommand import (
    CreateEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.DetachExecutionFromEvalCommand import (
    DetachExecutionFromEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.FreezeEvalCommand import (
    FreezeEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdateEvalCommand import (
    UpdateEvalCommand,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_summary import EvalBaselineRepo
from syn_domain.contexts.orchestration.slices.list_evals.projection import EvalListProjection
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.testing.stored_replay import replay

pytestmark = pytest.mark.unit

_EVAL = EvalId("eval-refactor")
_OTHER = EvalId("eval-other")
_API_SHA = "a" * 40
_WEB_SHA = "b" * 40


def _pin(slug: str, sha: str, ref: str) -> RepositoryBaseline:
    return RepositoryBaseline(
        repository=RepositoryRef.from_slug(slug), requested_ref=ref, commit_sha=sha
    )


class _Stream:
    """Real Eval and Execution repositories over one in-memory event store."""

    def __init__(self) -> None:
        self.client = MemoryEventStoreClient()
        self.evals = RepositoryAdapter(
            EventStoreRepository(self.client, EvalAggregate, "Eval")  # type: ignore[arg-type]  # ESP SDK TEvent invariance
        )
        self.executions = RepositoryAdapter(
            EventStoreRepository(
                self.client,
                WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowExecution",
            )
        )

    async def create_eval(self, eval_id: EvalId, name: str, tags: list[str]) -> None:
        aggregate = EvalAggregate()
        aggregate.create(
            CreateEvalCommand(
                eval_id=eval_id,
                name=name,
                goal=Goal(f"Goal of {name}"),
                baseline_repos=(
                    _pin("acme/web", _WEB_SHA, "v2"),
                    _pin("acme/api", _API_SHA, "main"),
                ),
                tags=TagSet(tags),
            )
        )
        await self.evals.save_new(aggregate)

    async def on_eval(self, eval_id: EvalId, act: str) -> None:
        aggregate = await self.evals.get_by_id(str(eval_id))
        assert aggregate is not None
        if act == "rename":
            aggregate.update(
                UpdateEvalCommand(
                    eval_id=eval_id, name="Refactor quality v2", add_tags=TagSet(["candidate"])
                )
            )
        elif act == "freeze":
            aggregate.freeze(FreezeEvalCommand(eval_id=eval_id))
        else:
            aggregate.archive(ArchiveEvalCommand(eval_id=eval_id, archived_by="ops"))
        await self.evals.save(aggregate)

    async def launch(self, execution_id: str, eval_id: EvalId | None, tags: list[str]) -> None:
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
            StartExecutionCommand(
                execution_id=execution_id,
                workflow_id="wf-1",
                workflow_name="Refactor",
                total_phases=1,
                inputs={},
                tags=TagSet(tags),
                launch_eval=(
                    None if eval_id is None else LaunchEval(eval_id, EvalSelection.EXPLICIT)
                ),
            )
        )
        await self.executions.save_new(aggregate)

    async def attach(self, execution_id: str, eval_id: EvalId) -> None:
        aggregate = await self.executions.get_by_id(execution_id)
        assert aggregate is not None
        aggregate.attach_to_eval(
            AttachExecutionToEvalCommand(aggregate_id=execution_id, eval_id=eval_id)
        )
        await self.executions.save(aggregate)

    async def detach(self, execution_id: str, eval_id: EvalId) -> None:
        aggregate = await self.executions.get_by_id(execution_id)
        assert aggregate is not None
        aggregate.detach_from_eval(
            DetachExecutionFromEvalCommand(aggregate_id=execution_id, eval_id=eval_id)
        )
        await self.executions.save(aggregate)

    async def fail(self, execution_id: str) -> None:
        aggregate = await self.executions.get_by_id(execution_id)
        assert aggregate is not None
        aggregate.fail_execution(
            FailExecutionCommand(
                execution_id=execution_id,
                error="boom",
                error_type=None,
                failed_phase_id=None,
                completed_phases=0,
                total_phases=1,
                classification=FailureClassification.UNCLASSIFIED,
            )
        )
        await self.executions.save(aggregate)


async def _fixture() -> _Stream:
    stream = _Stream()
    await stream.create_eval(_EVAL, "Refactor quality", ["nightly"])
    await stream.create_eval(_OTHER, "Other experiment", ["smoke"])
    await stream.on_eval(_EVAL, "rename")
    await stream.on_eval(_EVAL, "freeze")
    await stream.launch("run-launched", _EVAL, ["baseline"])
    await stream.launch("run-attached", None, ["candidate"])
    await stream.attach("run-attached", _EVAL)
    await stream.launch("run-detached", None, ["baseline"])
    await stream.attach("run-detached", _EVAL)
    await stream.detach("run-detached", _EVAL)
    await stream.launch("run-ordinary", None, ["baseline"])
    await stream.fail("run-launched")
    await stream.on_eval(_EVAL, "archive")
    return stream


async def _replayed(stream: _Stream, *, times: int) -> EvalListProjection:
    store = InMemoryProjectionStore()
    evals = EvalListProjection(store)
    executions = WorkflowExecutionListProjection(store)
    for _ in range(times):
        await replay(stream.client, MemoryCheckpointStore(), evals, executions)
    return evals


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.projection_count import GroupKey


class _GroupingStore(InMemoryProjectionStore):
    """Answers ``count_by`` itself and records that it was asked.

    The Eval list's tallies must come from the store's groups (#967): reading
    every member row to count them is the cost the grouping exists to remove.
    """

    def __init__(self) -> None:
        super().__init__()
        self.grouped: list[tuple[str, tuple[str, ...]]] = []

    async def count_by(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, str | Sequence[str]] | None = None,
    ) -> list[tuple[GroupKey, int]]:
        self.grouped.append((projection, tuple(fields)))
        rows = await super().query(projection, dict(filters) if filters else None)
        counts = Counter(tuple(row.get(field) for field in fields) for row in rows)
        return list(counts.items())


class TestReplay:
    async def test_eval_detail_has_baseline_and_current_members(self) -> None:
        evals = await _replayed(await _fixture(), times=1)

        detail = await evals.detail(str(_EVAL))

        assert detail is not None
        record = detail.record
        assert record.name == "Refactor quality v2"
        assert record.goal == "Goal of Refactor quality"
        assert record.tags == ("candidate", "nightly")
        assert record.frozen
        assert record.archived
        # Canonical order (by repository), with the ref the caller named kept.
        assert record.baseline_repos == (
            EvalBaselineRepo(owner="acme", name="api", requested_ref="main", commit_sha=_API_SHA),
            EvalBaselineRepo(owner="acme", name="web", requested_ref="v2", commit_sha=_WEB_SHA),
        )
        members = {run.workflow_execution_id: run for run in detail.runs.rows}
        assert set(members) == {"run-launched", "run-attached"}
        assert members["run-launched"].association_kind == "launched"
        assert members["run-launched"].status == "failed"
        assert members["run-attached"].association_kind == "attached"
        assert detail.runs.total == 2
        assert detail.runs.status_counts == {"failed": 1, "running": 1}

    async def test_eval_list_counts_runs_by_status(self) -> None:
        evals = await _replayed(await _fixture(), times=1)

        page = await evals.page()

        rows = {row.record.eval_id: row for row in page.rows}
        assert page.total == 2
        assert page.status_counts == {"active": 1, "archived": 1}
        assert rows[str(_EVAL)].run_count == 2
        assert rows[str(_EVAL)].run_status_counts == {"failed": 1, "running": 1}
        assert rows[str(_OTHER)].run_count == 0

    async def test_eval_list_tallies_come_from_the_stores_groups(self) -> None:
        stream = await _fixture()
        store = _GroupingStore()
        evals = EvalListProjection(store)
        executions = WorkflowExecutionListProjection(store)
        await replay(stream.client, MemoryCheckpointStore(), evals, executions)

        page = await evals.page()

        rows = {row.record.eval_id: row for row in page.rows}
        assert store.grouped == [(WORKFLOW_EXECUTIONS, ("eval_id", "status"))]
        assert rows[str(_EVAL)].run_status_counts == {"failed": 1, "running": 1}
        assert rows[str(_OTHER)].run_count == 0

    async def test_replaying_twice_yields_identical_state(self) -> None:
        stream = await _fixture()
        once = await _replayed(stream, times=1)
        twice = await _replayed(stream, times=2)

        assert await twice.page() == await once.page()
        assert await twice.detail(str(_EVAL)) == await once.detail(str(_EVAL))

    async def test_replay_makes_no_external_call(self) -> None:
        stream = await _fixture()
        with (
            patch("socket.socket.connect", side_effect=AssertionError("network during replay")),
            patch("subprocess.Popen", side_effect=AssertionError("process during replay")),
        ):
            evals = await _replayed(stream, times=2)
        assert evals.SIDE_EFFECTS_ALLOWED is False


class TestQueries:
    async def test_execution_list_filters_by_eval_and_by_tag_with_exact_totals(self) -> None:
        stream = await _fixture()
        store = InMemoryProjectionStore()
        executions = WorkflowExecutionListProjection(store)
        await replay(stream.client, MemoryCheckpointStore(), executions)

        in_eval = await executions.page(eval_id=str(_EVAL))
        assert in_eval.total == 2
        baseline_in_eval = await executions.page(eval_id=str(_EVAL), tags=["baseline"])
        assert [r.workflow_execution_id for r in baseline_in_eval.rows] == ["run-launched"]
        assert baseline_in_eval.total == 1
        # The detached run is in no eval now, and an ordinary run never was.
        baseline = await executions.page(tags=["baseline"])
        assert baseline.total == 3
        assert await executions.page(eval_id=str(_OTHER)) == await executions.page(
            eval_id="eval-none"
        )
        assert (await executions.page(eval_id=str(_OTHER))).total == 0

    async def test_pages_report_the_total_they_were_cut_from(self) -> None:
        evals = await _replayed(await _fixture(), times=1)

        first = await evals.page(limit=1)
        second = await evals.page(offset=1, limit=1)
        assert first.total == second.total == 2
        assert len(first.rows) == len(second.rows) == 1
        assert first.rows[0].record.eval_id != second.rows[0].record.eval_id

        runs = await evals.detail(str(_EVAL), offset=1, limit=1)
        assert runs is not None
        assert runs.runs.total == 2
        assert len(runs.runs.rows) == 1

    async def test_eval_list_filters(self) -> None:
        evals = await _replayed(await _fixture(), times=1)

        assert [r.record.eval_id for r in (await evals.page(statuses=["active"])).rows] == [
            str(_OTHER)
        ]
        assert (await evals.page(tags=["nightly"])).total == 1
        assert (await evals.page(search="v2")).total == 1
        assert await evals.detail("eval-missing") is None
