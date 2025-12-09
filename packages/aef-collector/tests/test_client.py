"""Tests for the HTTP client."""

from datetime import UTC, datetime

import pytest

from aef_collector.client.http import EventCollectorClient
from aef_collector.events.types import CollectedEvent, EventType


@pytest.fixture
def sample_event() -> CollectedEvent:
    """Create a sample event for testing."""
    return CollectedEvent(
        event_id="abc123def456789012345678901234",
        event_type=EventType.SESSION_STARTED,
        session_id="session-123",
        timestamp=datetime.now(UTC),
        data={},
    )


class TestEventCollectorClient:
    """Tests for the HTTP client."""

    def test_initialization(self) -> None:
        """Client should initialize with defaults."""
        client = EventCollectorClient("http://localhost:8080")

        assert client.collector_url == "http://localhost:8080"
        assert client.batch_size == 100
        assert client.batch_interval_ms == 1000

    def test_initialization_strips_trailing_slash(self) -> None:
        """URL should not have trailing slash."""
        client = EventCollectorClient("http://localhost:8080/")

        assert client.collector_url == "http://localhost:8080"

    def test_agent_id_generation(self) -> None:
        """Agent ID should be generated if not provided."""
        client = EventCollectorClient("http://localhost:8080")

        assert client.agent_id.startswith("agent-")
        assert len(client.agent_id) > 6

    def test_agent_id_override(self) -> None:
        """Agent ID can be overridden."""
        client = EventCollectorClient("http://localhost:8080", agent_id="my-agent")

        assert client.agent_id == "my-agent"

    @pytest.mark.asyncio
    async def test_emit_adds_to_buffer(self, sample_event: CollectedEvent) -> None:
        """emit should add event to buffer."""
        client = EventCollectorClient("http://localhost:8080")
        await client.start()

        await client.emit(sample_event)

        assert client.buffer_size == 1

        await client._client.aclose() if client._client else None

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self) -> None:
        """Flushing empty buffer returns None."""
        client = EventCollectorClient("http://localhost:8080")
        await client.start()

        result = await client.flush()

        assert result is None

        await client._client.aclose() if client._client else None

    @pytest.mark.asyncio
    async def test_stats_tracking(self, sample_event: CollectedEvent) -> None:
        """Stats should be tracked."""
        client = EventCollectorClient("http://localhost:8080")
        await client.start()

        await client.emit(sample_event)

        stats = client.stats
        assert stats["buffer_size"] == 1
        assert stats["events_sent"] == 0

        await client._client.aclose() if client._client else None

    def test_batch_id_generation(self) -> None:
        """Batch ID should include timestamp."""
        client = EventCollectorClient("http://localhost:8080")

        batch_id = client._generate_batch_id()

        assert batch_id.startswith("batch-")
        assert len(batch_id) > 20


class TestEventCollectorClientIntegration:
    """Integration tests for HTTP client (require mock server)."""

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Client should work as context manager."""
        # This test just verifies the context manager works
        # Real HTTP calls would need a mock server

        async with EventCollectorClient("http://localhost:8080") as client:
            assert client._client is not None

        # Client should be closed after context
        # (flush is called, but will fail without server)
