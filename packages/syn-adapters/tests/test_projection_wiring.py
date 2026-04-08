"""Behavioral tests for projection wiring: restart resilience and store guards.

Validates that:
- Projections rebuild identical state after clear + replay (restart resilience)
- InMemory stores reject non-test environments
- Factory functions gate correctly on environment
"""

from __future__ import annotations

import os

# Must be set before any syn_* imports
os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import Any

import pytest
from event_sourcing import (
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    MemoryCheckpointStore,
)

from syn_adapters.projection_stores.memory_store import (
    InMemoryProjectionStore,
    InMemoryProjectionStoreError,
)
from syn_adapters.projections.trigger_query_projection import (
    NS_DELIVERIES,
    NS_FIRE_RECORDS,
    NS_TRIGGER_INDEX,
    TriggerQueryProjection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    event_type: str,
    data: dict[str, Any],
    aggregate_id: str = "tr-test-001",
    global_nonce: int = 1,
) -> EventEnvelope[GenericDomainEvent]:
    """Build an EventEnvelope for testing projection handlers."""
    event = GenericDomainEvent(**data)
    metadata = EventMetadata(
        event_type=event_type,
        aggregate_id=aggregate_id,
        aggregate_type="TriggerRule",
        aggregate_nonce=global_nonce,
        global_nonce=global_nonce,
    )
    return EventEnvelope(event=event, metadata=metadata)


def _trigger_registered_data(
    trigger_id: str = "tr-test-001",
    event: str = "check_run.completed",
    repository: str = "owner/repo",
    workflow_id: str = "wf-001",
) -> dict[str, Any]:
    return {
        "trigger_id": trigger_id,
        "name": f"{event} → {workflow_id}",
        "event": event,
        "repository": repository,
        "workflow_id": workflow_id,
        "conditions": [],
        "config": {},
        "installation_id": "inst-001",
        "created_by": "test",
    }


def _trigger_fired_data(
    trigger_id: str = "tr-test-001",
    execution_id: str = "exec-001",
    webhook_delivery_id: str = "del-001",
) -> dict[str, Any]:
    return {
        "trigger_id": trigger_id,
        "execution_id": execution_id,
        "webhook_delivery_id": webhook_delivery_id,
        "matched_event_type": "check_run.completed",
        "repository": "owner/repo",
        "workflow_id": "wf-001",
        "fired_at": "2026-01-01T00:00:00Z",
    }


def _trigger_paused_data(trigger_id: str = "tr-test-001") -> dict[str, Any]:
    return {"trigger_id": trigger_id}


# ---------------------------------------------------------------------------
# Store guard tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreGuards:
    """Verify in-memory stores reject non-test environments."""

    def test_inmemory_projection_store_requires_test_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """InMemoryProjectionStore must raise outside test environment."""
        from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore

        monkeypatch.setenv("APP_ENVIRONMENT", "selfhost")
        # Clear cached settings so the new env var takes effect
        from syn_shared.settings.config import reset_settings

        reset_settings()

        with pytest.raises(InMemoryProjectionStoreError):
            InMemoryProjectionStore()

        # Restore
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        reset_settings()

    def test_trigger_query_store_returns_inmemory_in_test(self) -> None:
        """get_trigger_query_store() must return InMemory variant in test mode."""
        from syn_domain.contexts.github._shared.trigger_query_store import (
            InMemoryTriggerQueryStore,
            get_trigger_query_store,
            reset_trigger_store,
        )

        reset_trigger_store()
        store = get_trigger_query_store()
        assert isinstance(store, InMemoryTriggerQueryStore)
        reset_trigger_store()


# ---------------------------------------------------------------------------
# Restart resilience tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestRestartResilience:
    """Projections must rebuild identical state from replayed events."""

    async def test_trigger_projection_survives_restart(self) -> None:
        """Register a trigger, clear, replay — state must be identical."""
        store = InMemoryProjectionStore()
        checkpoint_store = MemoryCheckpointStore()
        projection = TriggerQueryProjection(store)

        trigger_id = "tr-restart-001"
        envelope = _make_envelope(
            "github.TriggerRegistered",
            _trigger_registered_data(trigger_id=trigger_id),
            aggregate_id=trigger_id,
            global_nonce=1,
        )

        # Phase 1: initial projection
        await projection.handle_event(envelope, checkpoint_store)
        original = await store.get(NS_TRIGGER_INDEX, trigger_id)
        assert original is not None
        assert original["status"] == "active"
        assert original["trigger_id"] == trigger_id

        # Phase 2: simulate restart — clear everything
        store.clear()
        cleared = await store.get(NS_TRIGGER_INDEX, trigger_id)
        assert cleared is None

        # Phase 3: replay
        await projection.handle_event(envelope, checkpoint_store)
        rebuilt = await store.get(NS_TRIGGER_INDEX, trigger_id)
        assert rebuilt is not None
        assert rebuilt["status"] == original["status"]
        assert rebuilt["trigger_id"] == original["trigger_id"]
        assert rebuilt["event"] == original["event"]

    async def test_multi_event_replay_across_namespaces(self) -> None:
        """Register + fire + pause — all 3 namespaces must rebuild identically."""
        store = InMemoryProjectionStore()
        checkpoint_store = MemoryCheckpointStore()
        projection = TriggerQueryProjection(store)

        trigger_id = "tr-multi-001"

        events = [
            _make_envelope(
                "github.TriggerRegistered",
                _trigger_registered_data(trigger_id=trigger_id),
                aggregate_id=trigger_id,
                global_nonce=1,
            ),
            _make_envelope(
                "github.TriggerFired",
                _trigger_fired_data(trigger_id=trigger_id, execution_id="exec-1"),
                aggregate_id=trigger_id,
                global_nonce=2,
            ),
            _make_envelope(
                "github.TriggerPaused",
                _trigger_paused_data(trigger_id=trigger_id),
                aggregate_id=trigger_id,
                global_nonce=3,
            ),
        ]

        # Phase 1: build
        for env in events:
            await projection.handle_event(env, checkpoint_store)

        original_index = await store.get(NS_TRIGGER_INDEX, trigger_id)
        original_fires = await store.get_all(NS_FIRE_RECORDS)
        original_deliveries = await store.get_all(NS_DELIVERIES)

        assert original_index is not None
        assert original_index["status"] == "paused"
        assert original_index["fire_count"] == 1
        assert len(original_fires) >= 1
        assert len(original_deliveries) >= 1

        # Phase 2: clear
        store.clear()
        assert await store.get(NS_TRIGGER_INDEX, trigger_id) is None
        assert len(await store.get_all(NS_FIRE_RECORDS)) == 0

        # Phase 3: replay
        for env in events:
            await projection.handle_event(env, checkpoint_store)

        rebuilt_index = await store.get(NS_TRIGGER_INDEX, trigger_id)
        rebuilt_fires = await store.get_all(NS_FIRE_RECORDS)
        rebuilt_deliveries = await store.get_all(NS_DELIVERIES)

        assert rebuilt_index is not None
        assert rebuilt_index["status"] == original_index["status"]
        assert rebuilt_index["fire_count"] == original_index["fire_count"]
        assert len(rebuilt_fires) == len(original_fires)
        assert len(rebuilt_deliveries) == len(original_deliveries)
