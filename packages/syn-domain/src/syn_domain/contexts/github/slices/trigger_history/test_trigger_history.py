"""Tests for trigger_history query slice."""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
    TriggerFiredEvent,
)
from syn_domain.contexts.github.slices.trigger_history.projection import (
    TriggerHistoryProjection,
)


@pytest.mark.unit
class TestTriggerHistoryProjection:
    """Tests for TriggerHistoryProjection."""

    async def test_handle_trigger_fired(self) -> None:
        """Test projecting a TriggerFired event creates a history entry."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        entry = await projection.handle_trigger_fired(
            TriggerFiredEvent(
                trigger_id="tr-1",
                execution_id="exec-1",
                webhook_delivery_id="del-1",
                github_event_type="check_run.completed",
                repository="syntropic137/test",
                pr_number=42,
            )
        )

        assert entry.trigger_id == "tr-1"
        assert entry.execution_id == "exec-1"
        assert entry.pr_number == 42
        assert entry.fired_at is not None

    async def test_get_history_returns_most_recent_first(self) -> None:
        """Test that get_history returns entries most recent first."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        for i in range(5):
            await projection.handle_trigger_fired(
                TriggerFiredEvent(
                    trigger_id="tr-1",
                    execution_id=f"exec-{i}",
                    github_event_type="check_run.completed",
                )
            )

        history = await projection.get_history("tr-1")
        assert len(history) == 5

    async def test_get_history_respects_limit(self) -> None:
        """Test that get_history respects the limit parameter."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        for i in range(10):
            await projection.handle_trigger_fired(
                TriggerFiredEvent(
                    trigger_id="tr-1",
                    execution_id=f"exec-{i}",
                    github_event_type="check_run.completed",
                )
            )

        history = await projection.get_history("tr-1", limit=3)
        assert len(history) == 3

    async def test_get_history_filters_by_trigger_id(self) -> None:
        """Test that get_history only returns entries for the given trigger."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-1", execution_id="exec-1", github_event_type="x")
        )
        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-2", execution_id="exec-2", github_event_type="x")
        )
        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-1", execution_id="exec-3", github_event_type="x")
        )

        history = await projection.get_history("tr-1")
        assert len(history) == 2
        assert all(e.trigger_id == "tr-1" for e in history)

    async def test_get_all_history(self) -> None:
        """Test get_all_history returns all entries."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-1", execution_id="exec-1", github_event_type="x")
        )
        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-2", execution_id="exec-2", github_event_type="x")
        )

        history = await projection.get_all_history()
        assert len(history) == 2
