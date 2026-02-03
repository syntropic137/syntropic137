"""Projection for token usage metrics.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to observation events from aef-collector:
- token_usage
"""

from typing import Any

from aef_domain.contexts.agent_sessions.domain.read_models.token_metrics import (
    SessionTokenMetrics,
    TokenUsageRecord,
)


class TokenMetricsProjection:
    """Builds token usage metrics from observation events.

    This projection maintains token usage records for each session,
    enabling queries like "how many tokens were used in session X".

    Note: This uses Pattern 2 (Event Log + CQRS) - observations flow
    directly to this projection without aggregate validation.
    See ADR-018 for architectural rationale.
    """

    PROJECTION_NAME = "token_metrics"

    def __init__(self, store: Any):
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_token_usage(self, event_data: dict[str, Any]) -> None:
        """Handle token_usage observation.

        Creates a token usage record for a message.
        """
        session_id = event_data.get("session_id")
        message_uuid = event_data.get("message_uuid")

        if not session_id or not message_uuid:
            return

        input_tokens = event_data.get("input_tokens", 0)
        output_tokens = event_data.get("output_tokens", 0)

        record = {
            "event_id": event_data.get("event_id", ""),
            "session_id": session_id,
            "message_uuid": message_uuid,
            "timestamp": event_data.get("timestamp"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_tokens": event_data.get("cache_creation_input_tokens", 0),
            "cache_read_tokens": event_data.get("cache_read_input_tokens", 0),
            "total_tokens": input_tokens + output_tokens,
        }

        # Store by session_id#message_uuid for deduplication
        key = f"{session_id}#{message_uuid}"
        await self._store.save(self.PROJECTION_NAME, key, record)

    async def get_metrics(self, session_id: str) -> SessionTokenMetrics:
        """Get aggregated token metrics for a session.

        Args:
            session_id: The session to get metrics for.

        Returns:
            SessionTokenMetrics with all token records for the session.
        """
        # Query all records for this session
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"session_id": session_id},
            order_by="timestamp",
        )

        records = [TokenUsageRecord.from_dict(d) for d in data]
        return SessionTokenMetrics.from_records(session_id, records)

    async def get_all(self) -> list[TokenUsageRecord]:
        """Get all token usage records across all sessions."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [TokenUsageRecord.from_dict(d) for d in data]
