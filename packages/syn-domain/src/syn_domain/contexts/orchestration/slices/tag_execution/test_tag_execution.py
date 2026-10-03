"""Tests for the tag-execution slice (#967).

Driven through the real handlers, the real aggregate and a real event-store
repository; only the store itself is in memory. Every assertion about tags is
made on a fresh load of the stream, so it is what replay rebuilds.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration._shared.tags import MAX_TAGS, TagSet
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
from syn_domain.contexts.orchestration.slices.tag_execution import (
    AddExecutionTagsHandler,
    RemoveExecutionTagsHandler,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.execution_tags import (
        ExecutionTags,
    )

EXECUTION_ID = "exec-tags"


class _Publisher:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        self.events.extend(e.event for e in events)


def _repository() -> RepositoryAdapter[WorkflowExecutionAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowExecution",
        )
    )


async def _launched_with(
    repository: RepositoryAdapter[WorkflowExecutionAggregate], tags: list[str]
) -> None:
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-1",
            workflow_name="Tagged",
            total_phases=1,
            inputs={},
            tags=TagSet(tags),
        )
    )
    await repository.save_new(aggregate)


async def _replayed(repository: RepositoryAdapter[WorkflowExecutionAggregate]) -> ExecutionTags:
    reloaded = await repository.get_by_id(EXECUTION_ID)
    assert reloaded is not None
    return reloaded.tags


@pytest.mark.unit
class TestAddExecutionTags:
    async def test_adds_to_current_and_leaves_inherited_alone(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, ["nightly"])

        result = await AddExecutionTagsHandler(repository, publisher).handle(
            AddExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["baseline"]))
        )

        assert result is not None
        assert result.success
        replayed = await _replayed(repository)
        assert replayed.current == TagSet(["baseline", "nightly"])
        assert replayed.inherited == TagSet(["nightly"])
        assert [e.event_type for e in publisher.events] == ["ExecutionTagsAdded"]

    async def test_the_event_names_its_workflow(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, [])

        await AddExecutionTagsHandler(repository, publisher).handle(
            AddExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["x"]))
        )

        (added,) = publisher.events
        assert added.model_dump()["workflow_id"] == "wf-1"

    async def test_an_unknown_execution_is_none(self) -> None:
        result = await AddExecutionTagsHandler(_repository()).handle(
            AddExecutionTagsCommand(aggregate_id="nope", tags=TagSet(["x"]))
        )
        assert result is None


@pytest.mark.unit
class TestRemoveExecutionTags:
    async def test_an_inherited_tag_can_be_removed_and_is_still_inherited(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, ["nightly", "smoke"])

        result = await RemoveExecutionTagsHandler(repository, publisher).handle(
            RemoveExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["nightly"]))
        )

        assert result is not None
        assert result.success
        replayed = await _replayed(repository)
        assert replayed.current == TagSet(["smoke"])
        assert replayed.inherited == TagSet(["nightly", "smoke"])

    async def test_removing_absent_tags_writes_nothing(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, ["a"])

        result = await RemoveExecutionTagsHandler(repository, publisher).handle(
            RemoveExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["b"]))
        )

        assert result is not None
        assert result.success
        assert publisher.events == []


@pytest.mark.unit
class TestTagEditRules:
    """The edit rules ExecutionTags decides, read through the handlers that apply them."""

    async def test_the_added_event_carries_only_the_new_tags(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, ["nightly"])

        await AddExecutionTagsHandler(repository, publisher).handle(
            AddExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["nightly", "x"]))
        )

        (added,) = publisher.events
        assert added.model_dump()["tags"] == ["x"]

    async def test_adding_present_tags_writes_nothing(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, ["nightly"])

        result = await AddExecutionTagsHandler(repository, publisher).handle(
            AddExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["nightly"]))
        )

        assert result is not None
        assert result.success
        assert publisher.events == []

    @pytest.mark.parametrize("handler", [AddExecutionTagsHandler, RemoveExecutionTagsHandler])
    async def test_an_empty_edit_is_refused(
        self, handler: type[AddExecutionTagsHandler] | type[RemoveExecutionTagsHandler]
    ) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, ["a"])
        command_type = (
            AddExecutionTagsCommand
            if handler is AddExecutionTagsHandler
            else RemoveExecutionTagsCommand
        )

        result = await handler(repository, publisher).handle(
            command_type(aggregate_id=EXECUTION_ID, tags=TagSet())
        )

        assert result is not None
        assert not result.success
        assert "At least one tag is required" in result.error
        assert publisher.events == []

    async def test_adding_past_the_limit_is_refused(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _launched_with(repository, [f"t{i}" for i in range(MAX_TAGS)])

        result = await AddExecutionTagsHandler(repository, publisher).handle(
            AddExecutionTagsCommand(aggregate_id=EXECUTION_ID, tags=TagSet(["one-more"]))
        )

        assert result is not None
        assert not result.success
        assert publisher.events == []
        assert len((await _replayed(repository)).current) == MAX_TAGS
