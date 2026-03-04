"""Tests for observability store implementations."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from syn_collector.collector.store import (
    InMemoryObservabilityStore,
    _event_to_dict,
)
from syn_collector.events.types import CollectedEvent, EventType


@pytest.fixture
def sample_event() -> CollectedEvent:
    """Create a sample collected event."""
    return CollectedEvent(
        event_id="abc123def456789012345678901234",
        event_type=EventType.TOOL_EXECUTION_STARTED,
        session_id="session-456",
        timestamp=datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC),
        data={"tool_name": "Read", "tool_use_id": "tu_123"},
    )


class TestEventToDict:
    """Tests for CollectedEvent → dict mapping."""

    def test_maps_event_type_as_string(self, sample_event: CollectedEvent) -> None:
        """event_type should be the string value, not the enum."""
        result = _event_to_dict(sample_event)
        assert result["event_type"] == "tool_execution_started"

    def test_maps_session_id(self, sample_event: CollectedEvent) -> None:
        """session_id should be preserved."""
        result = _event_to_dict(sample_event)
        assert result["session_id"] == "session-456"

    def test_maps_timestamp_as_iso(self, sample_event: CollectedEvent) -> None:
        """timestamp should be ISO 8601 string."""
        result = _event_to_dict(sample_event)
        assert result["timestamp"] == "2026-03-03T12:00:00+00:00"

    def test_spreads_data_fields(self, sample_event: CollectedEvent) -> None:
        """Data dict fields should be spread into top-level."""
        result = _event_to_dict(sample_event)
        assert result["tool_name"] == "Read"
        assert result["tool_use_id"] == "tu_123"

    def test_includes_event_id(self, sample_event: CollectedEvent) -> None:
        """event_id should be included for downstream dedup/correlation."""
        result = _event_to_dict(sample_event)
        assert result["event_id"] == "abc123def456789012345678901234"

    def test_reserved_keys_not_overridden_by_data(self) -> None:
        """Reserved fields must not be overridden by keys in event.data."""
        event = CollectedEvent(
            event_id="safe-event-id-00000000000000",
            event_type=EventType.SESSION_STARTED,
            session_id="real-session",
            timestamp=datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC),
            data={"event_type": "INJECTED", "session_id": "INJECTED"},
        )
        result = _event_to_dict(event)
        assert result["event_type"] == "session_started"
        assert result["session_id"] == "real-session"

    def test_dict_compatible_with_agent_event_from_dict(self, sample_event: CollectedEvent) -> None:
        """Mapped dict should be parseable by AgentEvent.from_dict()."""
        from syn_adapters.events.models import AgentEvent

        result = _event_to_dict(sample_event)
        agent_event = AgentEvent.from_dict(result)

        assert agent_event.event_type == "tool_execution_started"
        assert agent_event.session_id == "session-456"


class TestInMemoryObservabilityStore:
    """Tests for InMemoryObservabilityStore."""

    @pytest.mark.asyncio
    async def test_write_event(self, sample_event: CollectedEvent) -> None:
        """write_event should store event dict."""
        store = InMemoryObservabilityStore()
        await store.write_event(sample_event)

        assert len(store.events) == 1
        assert store.events[0]["event_type"] == "tool_execution_started"

    @pytest.mark.asyncio
    async def test_write_batch(self) -> None:
        """write_batch should store multiple events."""
        store = InMemoryObservabilityStore()
        events = [
            CollectedEvent(
                event_id=f"event-{i:032d}",
                event_type=EventType.TOKEN_USAGE,
                session_id="session-123",
                timestamp=datetime.now(UTC),
                data={"input_tokens": i * 100},
            )
            for i in range(3)
        ]

        await store.write_batch(events)

        assert len(store.events) == 3

    def test_clear(self, sample_event: CollectedEvent) -> None:
        """clear should remove all events."""
        store = InMemoryObservabilityStore()
        store.events.append(_event_to_dict(sample_event))
        store.clear()
        assert len(store.events) == 0


class TestProductionGuard:
    """Tests for in-memory store production guard."""

    def test_raises_in_production(self) -> None:
        """InMemoryObservabilityStore should raise in production environment."""
        from syn_adapters.storage.in_memory import InMemoryStorageError
        from syn_shared.settings import get_settings

        get_settings.cache_clear()
        try:
            with (
                patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}),
                pytest.raises(InMemoryStorageError, match="test or offline"),
            ):
                InMemoryObservabilityStore()
        finally:
            get_settings.cache_clear()


class TestFailFast:
    """Tests for fail-fast behavior when no DB URL is provided."""

    def test_inmemory_store_blocked_in_production(self) -> None:
        """InMemoryObservabilityStore cannot be used as fallback in production."""
        from syn_adapters.storage.in_memory import InMemoryStorageError
        from syn_shared.settings import get_settings

        get_settings.cache_clear()
        try:
            with (
                patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}),
                pytest.raises(InMemoryStorageError),
            ):
                InMemoryObservabilityStore()
        finally:
            get_settings.cache_clear()
