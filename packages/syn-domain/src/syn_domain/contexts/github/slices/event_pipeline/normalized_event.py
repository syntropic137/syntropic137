"""NormalizedEvent — canonical representation of a GitHub event from any source."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime


class EventSource(StrEnum):
    """Origin of a GitHub event."""

    WEBHOOK = "webhook"
    EVENTS_API = "events_api"


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """A GitHub event normalized across webhook and Events API sources.

    The ``dedup_key`` is computed externally via ``compute_dedup_key`` and
    passed in at construction time, keeping this class a pure data object.
    """

    event_type: str
    """GitHub event type, e.g. ``"push"``, ``"pull_request"``."""

    action: str
    """Event action, e.g. ``"opened"``. Empty string for events without actions."""

    repository: str
    """Full repository name, e.g. ``"owner/repo"``."""

    installation_id: str
    """GitHub App installation ID."""

    dedup_key: str
    """Content-based deduplication key (identical for the same logical event
    regardless of source)."""

    source: EventSource
    """Whether this event came from a webhook or the Events API."""

    payload: dict[str, Any]
    """Full GitHub event payload."""

    received_at: datetime
    """Timestamp when the event was received or polled."""

    delivery_id: str = ""
    """X-GitHub-Delivery header (webhook only)."""

    events_api_id: str = ""
    """Events API event ID (polling only)."""
