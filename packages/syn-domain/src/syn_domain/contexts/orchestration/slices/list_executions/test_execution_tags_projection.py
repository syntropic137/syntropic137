"""Execution tags on the read side (#967).

#959: the read models are derived from events and nothing else, so the tags
are asserted on FRESH projections that replay what a real repository wrote --
read back off the store in global order and dispatched through
``handle_event``, the same entry point the coordinator uses.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.AddExecutionTagsCommand import (
    AddExecutionTagsCommand,
)
from syn_domain.contexts.orchestration.domain.commands.RemoveExecutionTagsCommand import (
    RemoveExecutionTagsCommand,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.testing.stored_replay import replay


class _Store:
    """A real repository over an in-memory event store, and its replay."""

    def __init__(self) -> None:
        self.client = MemoryEventStoreClient()
        self.repository = RepositoryAdapter(
            EventStoreRepository(
                self.client,
                WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowExecution",
            )
        )

    async def launch(self, execution_id: str, tags: list[str]) -> None:
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
            StartExecutionCommand(
                execution_id=execution_id,
                workflow_id="wf-1",
                workflow_name="Tagged",
                total_phases=1,
                inputs={},
                tags=TagSet(tags),
            )
        )
        await self.repository.save_new(aggregate)

    async def add(self, execution_id: str, tags: list[str]) -> None:
        aggregate = await self.repository.get_by_id(execution_id)
        assert aggregate is not None
        aggregate.add_tags(AddExecutionTagsCommand(aggregate_id=execution_id, tags=TagSet(tags)))
        await self.repository.save(aggregate)

    async def remove(self, execution_id: str, tags: list[str]) -> None:
        aggregate = await self.repository.get_by_id(execution_id)
        assert aggregate is not None
        aggregate.remove_tags(
            RemoveExecutionTagsCommand(aggregate_id=execution_id, tags=TagSet(tags))
        )
        await self.repository.save(aggregate)

    async def replay_into(
        self, *projections: WorkflowExecutionListProjection | WorkflowExecutionDetailProjection
    ) -> None:
        await replay(self.client, MemoryCheckpointStore(), *projections)


def _fresh() -> tuple[WorkflowExecutionListProjection, WorkflowExecutionDetailProjection]:
    return (
        WorkflowExecutionListProjection(InMemoryProjectionStore()),
        WorkflowExecutionDetailProjection(InMemoryProjectionStore()),
    )


@pytest.mark.unit
class TestReplayRebuildsTheTags:
    async def test_launch_snapshot_and_later_edits_replay_into_fresh_projections(self) -> None:
        store = _Store()
        await store.launch("e1", ["nightly", "smoke"])
        await store.add("e1", ["baseline"])
        await store.remove("e1", ["nightly"])

        listing, detail = _fresh()
        await store.replay_into(listing, detail)

        summary = await listing.get_by_id("e1")
        full = await detail.get_by_id("e1")
        assert summary is not None
        assert full is not None
        for row in (summary, full):
            assert row.tags == ("baseline", "smoke")
            assert row.inherited_tags == ("nightly", "smoke")

    async def test_an_untagged_launch_replays_as_no_tags(self) -> None:
        store = _Store()
        await store.launch("e1", [])

        listing, detail = _fresh()
        await store.replay_into(listing, detail)

        summary = await listing.get_by_id("e1")
        full = await detail.get_by_id("e1")
        assert summary is not None
        assert full is not None
        assert summary.tags == summary.inherited_tags == ()
        assert full.tags == full.inherited_tags == ()

    async def test_a_start_event_written_before_tags_existed_reads_as_untagged(self) -> None:
        listing, detail = _fresh()
        pre_967 = {
            "execution_id": "old",
            "workflow_id": "wf-1",
            "workflow_name": "Old",
            "started_at": datetime.now(UTC).isoformat(),
            "total_phases": 1,
            "inputs": {},
        }
        await listing.on_workflow_execution_started(pre_967)
        await detail.on_workflow_execution_started(pre_967)

        summary = await listing.get_by_id("old")
        full = await detail.get_by_id("old")
        assert summary is not None
        assert full is not None
        assert summary.tags == full.tags == ()


@pytest.mark.unit
class TestFilteringByTag:
    @staticmethod
    async def _three_runs() -> WorkflowExecutionListProjection:
        store = _Store()
        await store.launch("both", ["a", "b"])
        await store.launch("only-a", ["a"])
        await store.launch("none", [])
        listing, _ = _fresh()
        await store.replay_into(listing)
        return listing

    async def test_a_tag_no_execution_carries_returns_zero_rows(self) -> None:
        listing = await self._three_runs()

        page = await listing.page(tags=["no-such-tag"])

        assert page.rows == []
        assert page.total == 0

    async def test_several_tags_are_anded(self) -> None:
        listing = await self._three_runs()

        page = await listing.page(tags=["a", "b"])

        assert [r.workflow_execution_id for r in page.rows] == ["both"]
        assert page.total == 1

    async def test_one_tag_matches_every_run_carrying_it(self) -> None:
        listing = await self._three_runs()

        page = await listing.page(tags=["a"])

        assert sorted(r.workflow_execution_id for r in page.rows) == ["both", "only-a"]

    async def test_no_tags_means_no_tag_filter(self) -> None:
        listing = await self._three_runs()

        assert (await listing.page(tags=None)).total == 3
        assert (await listing.page(tags=[])).total == 3

    async def test_the_filter_reads_current_tags_not_inherited(self) -> None:
        store = _Store()
        await store.launch("e1", ["a"])
        await store.remove("e1", ["a"])
        listing, _ = _fresh()
        await store.replay_into(listing)

        assert (await listing.page(tags=["a"])).total == 0
