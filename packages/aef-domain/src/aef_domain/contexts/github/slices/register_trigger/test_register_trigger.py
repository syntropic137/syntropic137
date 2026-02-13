"""Tests for RegisterTriggerHandler."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
    InMemoryTriggerQueryStore,
)


def _make_command(**overrides) -> RegisterTriggerCommand:
    """Create a RegisterTriggerCommand with sensible defaults."""
    defaults = {
        "name": "ci-self-heal",
        "event": "check_run.completed",
        "conditions": ({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        "repository": "AgentParadise/my-project",
        "installation_id": "inst-123",
        "workflow_id": "ci-fix-workflow",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return RegisterTriggerCommand(**defaults)


@pytest.mark.unit
class TestRegisterTriggerHandler:
    """Tests for RegisterTriggerHandler."""

    @pytest.mark.asyncio
    async def test_register_creates_and_persists(self) -> None:
        """Test that handler creates aggregate and indexes in query store."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store)

        aggregate = await handler.handle(_make_command())

        assert aggregate.trigger_id.startswith("tr-")
        assert aggregate.status == TriggerStatus.ACTIVE

        # Query store has the indexed trigger
        indexed = await store.get(aggregate.trigger_id)
        assert indexed is not None
        assert indexed.name == "ci-self-heal"
        assert indexed.status == "active"

    @pytest.mark.asyncio
    async def test_register_multiple_triggers(self) -> None:
        """Test registering multiple triggers."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store)

        t1 = await handler.handle(_make_command(name="trigger-1"))
        t2 = await handler.handle(_make_command(name="trigger-2"))

        assert t1.trigger_id != t2.trigger_id
        all_triggers = await store.list_all()
        assert len(all_triggers) == 2
