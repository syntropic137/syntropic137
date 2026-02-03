"""Tests for token metrics projection."""

import pytest

from aef_adapters.projection_stores import InMemoryProjectionStore
from aef_domain.contexts.agent_sessions.domain.queries import GetTokenMetricsQuery
from aef_domain.contexts.agent_sessions.slices.token_metrics import (
    TokenMetricsHandler,
    TokenMetricsProjection,
)


@pytest.fixture
def memory_store() -> InMemoryProjectionStore:
    """Create an in-memory projection store."""
    return InMemoryProjectionStore()


@pytest.fixture
def projection(memory_store: InMemoryProjectionStore) -> TokenMetricsProjection:
    """Create a token metrics projection with memory store."""
    return TokenMetricsProjection(memory_store)


@pytest.fixture
def handler(projection: TokenMetricsProjection) -> TokenMetricsHandler:
    """Create a token metrics handler."""
    return TokenMetricsHandler(projection)


@pytest.mark.unit
class TestTokenMetricsProjection:
    """Tests for TokenMetricsProjection."""

    @pytest.mark.asyncio
    async def test_on_token_usage(self, projection: TokenMetricsProjection) -> None:
        """Test handling token_usage event."""
        event_data = {
            "event_id": "evt-123",
            "session_id": "session-abc",
            "message_uuid": "msg-001",
            "timestamp": "2025-12-09T10:30:00Z",
            "input_tokens": 1500,
            "output_tokens": 350,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 200,
        }

        await projection.on_token_usage(event_data)

        metrics = await projection.get_metrics("session-abc")
        assert metrics.message_count == 1
        assert metrics.total_input_tokens == 1500
        assert metrics.total_output_tokens == 350
        assert metrics.total_cache_creation_tokens == 500
        assert metrics.total_cache_read_tokens == 200
        assert metrics.total_tokens == 1850

    @pytest.mark.asyncio
    async def test_multiple_messages(self, projection: TokenMetricsProjection) -> None:
        """Test aggregating multiple token usage events."""
        # Message 1
        await projection.on_token_usage(
            {
                "event_id": "evt-1",
                "session_id": "session-xyz",
                "message_uuid": "msg-001",
                "timestamp": "2025-12-09T10:00:00Z",
                "input_tokens": 1000,
                "output_tokens": 200,
            }
        )

        # Message 2
        await projection.on_token_usage(
            {
                "event_id": "evt-2",
                "session_id": "session-xyz",
                "message_uuid": "msg-002",
                "timestamp": "2025-12-09T10:00:05Z",
                "input_tokens": 1200,
                "output_tokens": 300,
            }
        )

        # Message 3
        await projection.on_token_usage(
            {
                "event_id": "evt-3",
                "session_id": "session-xyz",
                "message_uuid": "msg-003",
                "timestamp": "2025-12-09T10:00:10Z",
                "input_tokens": 1500,
                "output_tokens": 400,
            }
        )

        metrics = await projection.get_metrics("session-xyz")
        assert metrics.message_count == 3
        assert metrics.total_input_tokens == 3700
        assert metrics.total_output_tokens == 900
        assert metrics.total_tokens == 4600

    @pytest.mark.asyncio
    async def test_deduplication_by_message_uuid(self, projection: TokenMetricsProjection) -> None:
        """Test that duplicate message_uuid events are deduplicated."""
        event_data = {
            "event_id": "evt-1",
            "session_id": "session-abc",
            "message_uuid": "msg-001",
            "timestamp": "2025-12-09T10:00:00Z",
            "input_tokens": 1000,
            "output_tokens": 200,
        }

        # Send same event twice (simulating retry)
        await projection.on_token_usage(event_data)
        await projection.on_token_usage(event_data)

        metrics = await projection.get_metrics("session-abc")
        # Should only count once (stored by session_id#message_uuid key)
        assert metrics.message_count == 1
        assert metrics.total_input_tokens == 1000

    @pytest.mark.asyncio
    async def test_empty_session(self, projection: TokenMetricsProjection) -> None:
        """Test getting metrics for session with no token usage."""
        metrics = await projection.get_metrics("nonexistent-session")
        assert metrics.message_count == 0
        assert metrics.total_tokens == 0


class TestTokenMetricsHandler:
    """Tests for TokenMetricsHandler."""

    @pytest.mark.asyncio
    async def test_handle_query(
        self,
        projection: TokenMetricsProjection,
        handler: TokenMetricsHandler,
    ) -> None:
        """Test handling GetTokenMetricsQuery."""
        await projection.on_token_usage(
            {
                "event_id": "evt-1",
                "session_id": "session-test",
                "message_uuid": "msg-001",
                "timestamp": "2025-12-09T10:00:00Z",
                "input_tokens": 500,
                "output_tokens": 100,
            }
        )

        query = GetTokenMetricsQuery(session_id="session-test")
        metrics = await handler.handle(query)

        assert metrics.session_id == "session-test"
        assert metrics.total_tokens == 600
        assert len(metrics.records) == 1

    @pytest.mark.asyncio
    async def test_handle_query_without_records(
        self,
        projection: TokenMetricsProjection,
        handler: TokenMetricsHandler,
    ) -> None:
        """Test excluding individual records from response."""
        await projection.on_token_usage(
            {
                "event_id": "evt-1",
                "session_id": "session-test",
                "message_uuid": "msg-001",
                "timestamp": "2025-12-09T10:00:00Z",
                "input_tokens": 500,
                "output_tokens": 100,
            }
        )
        await projection.on_token_usage(
            {
                "event_id": "evt-2",
                "session_id": "session-test",
                "message_uuid": "msg-002",
                "timestamp": "2025-12-09T10:00:05Z",
                "input_tokens": 600,
                "output_tokens": 150,
            }
        )

        query = GetTokenMetricsQuery(session_id="session-test", include_records=False)
        metrics = await handler.handle(query)

        assert metrics.total_tokens == 1350
        assert metrics.message_count == 2
        assert len(metrics.records) == 0  # Records excluded
