"""Trigger history projection.

Projects TriggerFired events into TriggerHistoryEntry read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.github.domain.read_models.trigger_history_entry import (
    TriggerHistoryEntry,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
        TriggerFiredEvent,
    )

logger = logging.getLogger(__name__)


class TriggerHistoryProjection:
    """Projects TriggerFired events into TriggerHistoryEntry read models."""

    def __init__(self) -> None:
        """Initialize the projection."""
        self._entries: list[TriggerHistoryEntry] = []

    def handle_trigger_fired(self, event: TriggerFiredEvent) -> TriggerHistoryEntry:
        """Handle a TriggerFired event."""
        entry = TriggerHistoryEntry(
            trigger_id=event.trigger_id,
            execution_id=event.execution_id,
            webhook_delivery_id=event.webhook_delivery_id,
            github_event_type=event.github_event_type,
            repository=event.repository,
            pr_number=event.pr_number,
            payload_summary=dict(event.payload_summary),
            fired_at=datetime.now(UTC),
        )
        self._entries.append(entry)
        logger.info(f"Projected TriggerFired: {event.trigger_id} -> {event.execution_id}")
        return entry

    def get_history(self, trigger_id: str, limit: int = 50) -> list[TriggerHistoryEntry]:
        """Get firing history for a trigger, most recent first."""
        matching = [e for e in self._entries if e.trigger_id == trigger_id]
        matching.sort(key=lambda e: e.fired_at or datetime.min, reverse=True)
        return matching[:limit]

    def get_all_history(self, limit: int = 50) -> list[TriggerHistoryEntry]:
        """Get all trigger firing history, most recent first."""
        entries = sorted(self._entries, key=lambda e: e.fired_at or datetime.min, reverse=True)
        return entries[:limit]


# Singleton
_projection: TriggerHistoryProjection | None = None


def get_trigger_history_projection() -> TriggerHistoryProjection:
    """Get the global trigger history projection instance."""
    global _projection
    if _projection is None:
        _projection = TriggerHistoryProjection()
    return _projection


def reset_trigger_history_projection() -> None:
    """Reset the global projection (for testing)."""
    global _projection
    _projection = None
