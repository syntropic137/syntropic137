"""Tests for RegisterTriggerHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.github._shared.trigger_query_store import (
    InMemoryTriggerQueryStore,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from syn_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)


class NullRepository:
    """No-op repository for unit tests that don't need persistence."""

    async def get_by_id(self, id):
        return None

    async def save(self, aggregate):
        pass


def _make_command(**overrides) -> RegisterTriggerCommand:
    """Create a RegisterTriggerCommand with sensible defaults."""
    defaults = {
        "name": "ci-self-heal",
        "event": "check_run.completed",
        "conditions": ({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        "repository": "syntropic137/my-project",
        "installation_id": "inst-123",
        "workflow_id": "ci-fix-workflow",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return RegisterTriggerCommand(**defaults)


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


@pytest.mark.unit
class TestRegisterTriggerHandler:
    """Tests for RegisterTriggerHandler."""

    @pytest.mark.asyncio
    async def test_register_creates_and_persists(self) -> None:
        """Test that handler creates aggregate with correct state."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store, repository=NullRepository())

        aggregate = await handler.handle(_make_command())

        assert aggregate.trigger_id.startswith("tr-")
        assert aggregate.status == TriggerStatus.ACTIVE
        assert aggregate.name == "ci-self-heal"

    @pytest.mark.asyncio
    async def test_register_multiple_triggers(self) -> None:
        """Test registering multiple triggers."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store, repository=NullRepository())

        t1 = await handler.handle(_make_command(name="trigger-1"))
        t2 = await handler.handle(_make_command(name="trigger-2"))

        assert t1.trigger_id != t2.trigger_id


@pytest.mark.unit
class TestDebounceSecondsRejected:
    """debounce_seconds is accepted nowhere it would be ignored (#1961)."""

    def test_non_zero_debounce_seconds_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="debounce_seconds is not supported"):
            _make_command(config=(("debounce_seconds", 60),))

    @pytest.mark.asyncio
    async def test_zero_debounce_seconds_still_registers(self) -> None:
        """The CLI always sends 0; that must keep working."""
        handler = RegisterTriggerHandler(
            store=InMemoryTriggerQueryStore(), repository=NullRepository()
        )

        aggregate = await handler.handle(
            _make_command(config=(("debounce_seconds", 0), ("cooldown_seconds", 120)))
        )

        assert aggregate.config.debounce_seconds == 0
        assert aggregate.config.cooldown_seconds == 120
