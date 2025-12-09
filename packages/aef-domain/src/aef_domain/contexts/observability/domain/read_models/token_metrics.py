"""Read models for token usage metrics."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TokenUsageRecord:
    """Single token usage record from a message.

    Represents an observed token usage from Claude transcript.
    This is Pattern 2 (Event Log + CQRS) - observations, not commands.
    """

    event_id: str
    """Deterministic event ID for deduplication."""

    session_id: str
    """Session this token usage belongs to."""

    message_uuid: str
    """Claude's message UUID for correlation."""

    timestamp: datetime | str
    """When the message was processed."""

    input_tokens: int
    """Number of input tokens."""

    output_tokens: int
    """Number of output tokens."""

    cache_creation_tokens: int = 0
    """Tokens used for cache creation."""

    cache_read_tokens: int = 0
    """Tokens read from cache."""

    total_tokens: int = 0
    """Total tokens (input + output)."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenUsageRecord":
        """Create from dictionary."""
        input_toks = data.get("input_tokens", 0)
        output_toks = data.get("output_tokens", 0)
        # timestamp is required, default to empty string if missing
        timestamp = data.get("timestamp") or ""

        return cls(
            event_id=data.get("event_id", ""),
            session_id=data.get("session_id", ""),
            message_uuid=data.get("message_uuid", ""),
            timestamp=timestamp,
            input_tokens=input_toks,
            output_tokens=output_toks,
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            total_tokens=data.get("total_tokens", input_toks + output_toks),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        ts = self.timestamp
        if isinstance(ts, datetime):
            ts = ts.isoformat()

        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "message_uuid": self.message_uuid,
            "timestamp": ts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class SessionTokenMetrics:
    """Aggregated token metrics for a session.

    Provides cumulative token usage across all messages in a session.
    """

    session_id: str
    """Session ID this metrics belongs to."""

    records: tuple[TokenUsageRecord, ...]
    """All token usage records in chronological order."""

    total_input_tokens: int
    """Total input tokens across all messages."""

    total_output_tokens: int
    """Total output tokens across all messages."""

    total_cache_creation_tokens: int
    """Total cache creation tokens."""

    total_cache_read_tokens: int
    """Total cache read tokens."""

    total_tokens: int
    """Total tokens (input + output)."""

    message_count: int
    """Number of messages with token usage."""

    @classmethod
    def from_records(
        cls,
        session_id: str,
        records: list[TokenUsageRecord],
    ) -> "SessionTokenMetrics":
        """Create metrics from list of records."""
        total_input = sum(r.input_tokens for r in records)
        total_output = sum(r.output_tokens for r in records)
        total_cache_creation = sum(r.cache_creation_tokens for r in records)
        total_cache_read = sum(r.cache_read_tokens for r in records)

        return cls(
            session_id=session_id,
            records=tuple(records),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_creation_tokens=total_cache_creation,
            total_cache_read_tokens=total_cache_read,
            total_tokens=total_input + total_output,
            message_count=len(records),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "records": [r.to_dict() for r in self.records],
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_creation_tokens": self.total_cache_creation_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_tokens": self.total_tokens,
            "message_count": self.message_count,
        }
