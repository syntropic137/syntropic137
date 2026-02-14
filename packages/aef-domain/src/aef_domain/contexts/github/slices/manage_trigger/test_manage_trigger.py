"""Tests for ManageTriggerHandler."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
    DeleteTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
    PauseTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
    ResumeTriggerCommand,
)
from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
    ManageTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
    InMemoryTriggerQueryStore,
)


class InMemoryRepository:
    """In-memory repository for tests that need aggregate persistence."""

    def __init__(self):
        self._store: dict = {}

    async def get_by_id(self, id):
        return self._store.get(id)

    async def save(self, aggregate):
        self._store[aggregate.trigger_id] = aggregate


async def _index_aggregate(store: InMemoryTriggerQueryStore, aggregate) -> None:
    """Manually index an aggregate in the query store (simulates projection)."""
    await store.index_trigger(
        trigger_id=aggregate.trigger_id,
        name=aggregate.name,
        event=aggregate.event,
        repository=aggregate.repository,
        workflow_id=aggregate.workflow_id,
        conditions=[
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in aggregate.conditions
        ],
        input_mapping=aggregate.input_mapping,
        config=aggregate.config,
        installation_id=aggregate.installation_id,
        created_by=aggregate.created_by,
        status=aggregate.status.value,
    )


async def _setup(store: InMemoryTriggerQueryStore) -> tuple[str, InMemoryRepository]:
    """Register a trigger and return (trigger_id, repository)."""
    repo = InMemoryRepository()
    handler = RegisterTriggerHandler(store=store, repository=repo)
    cmd = RegisterTriggerCommand(
        name="test-trigger",
        event="check_run.completed",
        conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        repository="AgentParadise/test",
        workflow_id="ci-fix-workflow",
        created_by="test",
    )
    aggregate = await handler.handle(cmd)
    await _index_aggregate(store, aggregate)
    return aggregate.trigger_id, repo


@pytest.mark.unit
class TestManageTriggerHandler:
    """Tests for ManageTriggerHandler."""

    @pytest.mark.asyncio
    async def test_pause_active_trigger(self) -> None:
        """Test pausing an active trigger."""
        store = InMemoryTriggerQueryStore()
        trigger_id, repo = await _setup(store)
        handler = ManageTriggerHandler(store=store, repository=repo)

        result = await handler.pause(PauseTriggerCommand(trigger_id=trigger_id, paused_by="admin"))

        assert result is not None
        # Simulate projection updating status
        await store.update_status(trigger_id, "paused")
        indexed = await store.get(trigger_id)
        assert indexed is not None
        assert indexed.status == "paused"

    @pytest.mark.asyncio
    async def test_pause_nonexistent_returns_none(self) -> None:
        """Test pausing a nonexistent trigger returns None."""
        store = InMemoryTriggerQueryStore()
        handler = ManageTriggerHandler(store=store, repository=InMemoryRepository())

        result = await handler.pause(
            PauseTriggerCommand(trigger_id="tr-nonexistent", paused_by="admin")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_paused_trigger(self) -> None:
        """Test resuming a paused trigger."""
        store = InMemoryTriggerQueryStore()
        trigger_id, repo = await _setup(store)
        handler = ManageTriggerHandler(store=store, repository=repo)

        await handler.pause(PauseTriggerCommand(trigger_id=trigger_id, paused_by="admin"))
        await store.update_status(trigger_id, "paused")

        result = await handler.resume(
            ResumeTriggerCommand(trigger_id=trigger_id, resumed_by="admin")
        )

        assert result is not None
        await store.update_status(trigger_id, "active")
        indexed = await store.get(trigger_id)
        assert indexed is not None
        assert indexed.status == "active"

    @pytest.mark.asyncio
    async def test_delete_trigger(self) -> None:
        """Test deleting a trigger."""
        store = InMemoryTriggerQueryStore()
        trigger_id, repo = await _setup(store)
        handler = ManageTriggerHandler(store=store, repository=repo)

        result = await handler.delete(
            DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="admin")
        )

        assert result is not None
        await store.update_status(trigger_id, "deleted")
        indexed = await store.get(trigger_id)
        assert indexed is not None
        assert indexed.status == "deleted"

    @pytest.mark.asyncio
    async def test_delete_already_deleted_returns_none(self) -> None:
        """Test deleting an already-deleted trigger returns None."""
        store = InMemoryTriggerQueryStore()
        trigger_id, repo = await _setup(store)
        handler = ManageTriggerHandler(store=store, repository=repo)

        await handler.delete(DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="admin"))
        await store.update_status(trigger_id, "deleted")

        result = await handler.delete(
            DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="admin")
        )
        assert result is None
