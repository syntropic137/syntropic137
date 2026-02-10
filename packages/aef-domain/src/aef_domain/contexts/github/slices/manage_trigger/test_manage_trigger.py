"""Tests for ManageTriggerHandler."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
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
    InMemoryTriggerStore,
)


async def _setup_trigger(store: InMemoryTriggerStore) -> str:
    """Register a trigger and return its ID."""
    handler = RegisterTriggerHandler(store=store)
    cmd = RegisterTriggerCommand(
        name="test-trigger",
        event="check_run.completed",
        conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        repository="AgentParadise/test",
        workflow_id="ci-fix-workflow",
        created_by="test",
    )
    aggregate = await handler.handle(cmd)
    return aggregate.trigger_id


@pytest.mark.unit
class TestManageTriggerHandler:
    """Tests for ManageTriggerHandler."""

    @pytest.mark.asyncio
    async def test_pause_active_trigger(self) -> None:
        """Test pausing an active trigger."""
        store = InMemoryTriggerStore()
        trigger_id = await _setup_trigger(store)
        handler = ManageTriggerHandler(store=store)

        event = await handler.pause(PauseTriggerCommand(trigger_id=trigger_id, paused_by="admin"))

        assert event is not None
        stored = await store.get(trigger_id)
        assert stored is not None
        assert stored.status == TriggerStatus.PAUSED

    @pytest.mark.asyncio
    async def test_pause_nonexistent_returns_none(self) -> None:
        """Test pausing a nonexistent trigger returns None."""
        store = InMemoryTriggerStore()
        handler = ManageTriggerHandler(store=store)

        result = await handler.pause(
            PauseTriggerCommand(trigger_id="tr-nonexistent", paused_by="admin")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_paused_trigger(self) -> None:
        """Test resuming a paused trigger."""
        store = InMemoryTriggerStore()
        trigger_id = await _setup_trigger(store)
        handler = ManageTriggerHandler(store=store)

        await handler.pause(PauseTriggerCommand(trigger_id=trigger_id, paused_by="admin"))
        event = await handler.resume(
            ResumeTriggerCommand(trigger_id=trigger_id, resumed_by="admin")
        )

        assert event is not None
        stored = await store.get(trigger_id)
        assert stored is not None
        assert stored.status == TriggerStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_delete_trigger(self) -> None:
        """Test deleting a trigger."""
        store = InMemoryTriggerStore()
        trigger_id = await _setup_trigger(store)
        handler = ManageTriggerHandler(store=store)

        event = await handler.delete(
            DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="admin")
        )

        assert event is not None
        stored = await store.get(trigger_id)
        assert stored is not None
        assert stored.status == TriggerStatus.DELETED

    @pytest.mark.asyncio
    async def test_delete_already_deleted_returns_none(self) -> None:
        """Test deleting an already-deleted trigger returns None."""
        store = InMemoryTriggerStore()
        trigger_id = await _setup_trigger(store)
        handler = ManageTriggerHandler(store=store)

        await handler.delete(DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="admin"))
        result = await handler.delete(
            DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="admin")
        )
        assert result is None
