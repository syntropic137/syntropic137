"""Tests for token metrics projection."""

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.agent_sessions.domain.queries import GetTokenMetricsQuery
from syn_domain.contexts.agent_sessions.slices.token_metrics import (
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
        # All four components (issue #873): 1500 + 350 + 500 + 200.
        assert metrics.total_tokens == 2550

    @pytest.mark.asyncio
    async def test_on_token_usage_reads_the_canonical_cache_field_names(
        self, projection: TokenMetricsProjection
    ) -> None:
        """token_usage events store cache_creation_tokens / cache_read_tokens.

        The projection previously only looked for the raw Anthropic API
        spelling (``cache_*_input_tokens``), so every real event contributed
        zero cache tokens (issue #873).
        """
        await projection.on_token_usage(
            {
                "event_id": "evt-873",
                "session_id": "session-873",
                "message_uuid": "msg-873",
                "timestamp": "2025-12-09T10:30:00Z",
                "input_tokens": 35,
                "output_tokens": 1708,
                "cache_creation_tokens": 59932,
                "cache_read_tokens": 57214,
            }
        )

        metrics = await projection.get_metrics("session-873")
        assert metrics.total_cache_creation_tokens == 59932
        assert metrics.total_cache_read_tokens == 57214
        assert metrics.total_tokens == 118889

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


@pytest.mark.unit
class TestStoredTotalTokensIsDerived:
    """``TokenUsageRecord.total_tokens`` is derived, never read from the row.

    Rows written before issue #873 carry a total that omits both cache
    components. ``from_dict`` is the only door those rows come back through
    (``get_metrics`` and ``get_all`` both use it), so trusting a stored total
    would hand the old wrong number straight back out for all of history.
    """

    def test_a_stale_stored_total_is_recomputed_not_trusted(self) -> None:
        """A pre-#873 row: total_tokens stored as input + output only."""
        from syn_domain.contexts.agent_sessions.domain.read_models.token_metrics import (
            TokenUsageRecord,
        )

        stale_row = {
            "event_id": "evt-pre-873",
            "session_id": "session-pre-873",
            "message_uuid": "msg-pre-873",
            "timestamp": "2025-12-09T10:00:00Z",
            "input_tokens": 35,
            "output_tokens": 1_708,
            "cache_creation_tokens": 59_932,
            "cache_read_tokens": 57_214,
            "total_tokens": 1_743,  # what the old projection wrote
        }

        record = TokenUsageRecord.from_dict(stale_row)

        assert record.total_tokens == 118_889, (
            "from_dict trusted the stored total; pre-#873 rows would keep "
            "reporting a total that omits both cache components"
        )
        assert record.total_tokens != stale_row["total_tokens"]

    def test_a_row_with_no_stored_total_still_sums_all_four(self) -> None:
        from syn_domain.contexts.agent_sessions.domain.read_models.token_metrics import (
            TokenUsageRecord,
        )

        record = TokenUsageRecord.from_dict(
            {
                "event_id": "evt-no-total",
                "session_id": "session-no-total",
                "message_uuid": "msg-no-total",
                "timestamp": "2025-12-09T10:00:00Z",
                "input_tokens": 35,
                "output_tokens": 1_708,
                "cache_creation_tokens": 59_932,
                "cache_read_tokens": 57_214,
            }
        )

        assert record.total_tokens == 118_889

    def test_a_round_trip_through_the_store_stays_reconciled(self) -> None:
        from syn_domain.contexts.agent_sessions.domain.read_models.token_metrics import (
            TokenUsageRecord,
        )

        original = TokenUsageRecord(
            event_id="evt-round-trip",
            session_id="session-round-trip",
            message_uuid="msg-round-trip",
            timestamp="2025-12-09T10:00:00Z",
            input_tokens=35,
            output_tokens=1_708,
            cache_creation_tokens=59_932,
            cache_read_tokens=57_214,
            total_tokens=1_743,  # deliberately wrong on the way in
        )

        restored = TokenUsageRecord.from_dict(original.to_dict())

        assert restored.total_tokens == 118_889
