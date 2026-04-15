"""Trigger history projection.

Projects TriggerFired events into TriggerHistoryEntry read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github._shared.projection_names import TRIGGER_HISTORY
from syn_domain.contexts.github.domain.read_models.trigger_history_entry import (
    TriggerHistoryEntry,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

    from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import (
        TriggerBlockedEvent,
    )
    from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
        TriggerFiredEvent,
    )

logger = logging.getLogger(__name__)

PROJECTION_NAME = TRIGGER_HISTORY


def _entry_to_dict(entry: TriggerHistoryEntry) -> dict[str, Any]:
    return {
        "trigger_id": entry.trigger_id,
        "execution_id": entry.execution_id,
        "webhook_delivery_id": entry.webhook_delivery_id,
        "github_event_type": entry.github_event_type,
        "repository": entry.repository,
        "pr_number": entry.pr_number,
        "payload_summary": entry.payload_summary,
        "fired_at": entry.fired_at.isoformat() if entry.fired_at else None,
        "status": entry.status,
        "cost_usd": entry.cost_usd,
        "guard_name": entry.guard_name,
        "block_reason": entry.block_reason,
    }


def _entry_from_dict(data: dict[str, Any]) -> TriggerHistoryEntry:
    return TriggerHistoryEntry(
        trigger_id=data["trigger_id"],
        execution_id=data["execution_id"],
        webhook_delivery_id=data.get("webhook_delivery_id", ""),
        github_event_type=data.get("github_event_type", ""),
        repository=data.get("repository", ""),
        pr_number=data.get("pr_number"),
        payload_summary=data.get("payload_summary", {}),
        fired_at=datetime.fromisoformat(data["fired_at"]) if data.get("fired_at") else None,
        status=data.get("status", "dispatched"),
        cost_usd=data.get("cost_usd"),
        guard_name=data.get("guard_name", ""),
        block_reason=data.get("block_reason", ""),
    )


def _entry_key(entry: TriggerHistoryEntry) -> str:
    """Unique store key: delivery ID if present, else trigger+execution."""
    if entry.webhook_delivery_id:
        return entry.webhook_delivery_id
    return f"{entry.trigger_id}_{entry.execution_id}"


class TriggerHistoryProjection:
    """Projects TriggerFired events into TriggerHistoryEntry read models."""

    def __init__(self, store: ProjectionStore) -> None:
        """Initialize the projection."""
        self._store = store

    async def handle_trigger_fired(self, event: TriggerFiredEvent) -> TriggerHistoryEntry:
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
        key = _entry_key(entry)
        data = _entry_to_dict(entry)
        data["_projection_key"] = key
        await self._store.save(PROJECTION_NAME, key, data)
        logger.info(f"Projected TriggerFired: {event.trigger_id} -> {event.execution_id}")
        return entry

    async def handle_trigger_blocked(
        self,
        event: TriggerBlockedEvent,
        global_nonce: int | None = None,  # noqa: ARG002 — kept for API compat; not used (see comment below)
    ) -> TriggerHistoryEntry:
        """Handle a TriggerBlocked event.

        Args:
            event: The blocked event data.
            global_nonce: Kept for API compatibility; not used for blocked entries (see NOTE below).
        """
        entry = TriggerHistoryEntry(
            trigger_id=event.trigger_id,
            execution_id="",
            webhook_delivery_id=event.webhook_delivery_id,
            github_event_type=event.github_event_type,
            repository=event.repository,
            pr_number=event.pr_number,
            payload_summary=dict(event.payload_summary),
            fired_at=datetime.now(UTC),
            status="blocked",
            guard_name=event.guard_name,
            block_reason=event.reason,
        )
        # Content-based key namespaced by trigger_id.
        # Blocked entries intentionally use the same key for the same logical event
        # so that rapid re-deliveries of the same event (e.g. poller bursts) overwrite
        # rather than accumulate. This deduplicates noise in trigger history without
        # hiding genuine new events (different guard, event type, or PR number).
        # NOTE: global_nonce is deliberately NOT used here — nonce-keyed blocked entries
        # would create one record per delivery, producing the noise we are eliminating.
        if entry.webhook_delivery_id:
            key = f"{entry.trigger_id}_blocked_{entry.webhook_delivery_id}"
        else:
            pr_part = str(entry.pr_number) if entry.pr_number is not None else "no_pr"
            # Use event-specific stable ID from payload_summary when available
            # (e.g. comment_id for issue_comment events) so distinct events on
            # the same PR are not over-deduplicated into a single entry.
            event_id = entry.payload_summary.get("comment_id")
            if event_id:
                key = f"{entry.trigger_id}_blocked_{entry.github_event_type}_{pr_part}_{event_id}"
            else:
                key = f"{entry.trigger_id}_blocked_{entry.guard_name}_{entry.github_event_type}_{pr_part}"
        data = _entry_to_dict(entry)
        data["_projection_key"] = key
        await self._store.save(PROJECTION_NAME, key, data)
        logger.info(f"Projected TriggerBlocked: {event.trigger_id} ({event.guard_name})")
        return entry

    async def get_history(self, trigger_id: str, limit: int = 50) -> list[TriggerHistoryEntry]:
        """Get firing history for a trigger, most recent first."""
        records = await self._store.get_all(PROJECTION_NAME)
        matching = [_entry_from_dict(r) for r in records if r.get("trigger_id") == trigger_id]
        matching.sort(key=lambda e: e.fired_at or datetime.min, reverse=True)
        return matching[:limit]

    async def get_all_history(self, limit: int = 50) -> list[TriggerHistoryEntry]:
        """Get all trigger firing history, most recent first."""
        records = await self._store.get_all(PROJECTION_NAME)
        entries = [_entry_from_dict(r) for r in records]
        entries.sort(key=lambda e: e.fired_at or datetime.min, reverse=True)
        return entries[:limit]

    async def clear_all_data(self) -> None:
        """Clear all projection data (for rebuild)."""
        records = await self._store.get_all(PROJECTION_NAME)
        for record in records:
            # Use stored key if available (handles blocked entries whose keys
            # can't be reconstructed from entry fields alone).
            key = record.get("_projection_key")
            if key is None:
                entry = _entry_from_dict(record)
                key = _entry_key(entry)
            await self._store.delete(PROJECTION_NAME, key)


# Singleton
_projection: TriggerHistoryProjection | None = None


def get_trigger_history_projection() -> TriggerHistoryProjection:
    """Get the global trigger history projection instance."""
    global _projection
    if _projection is None:
        from syn_adapters.projection_stores import get_projection_store

        _projection = TriggerHistoryProjection(store=get_projection_store())
    return _projection


def reset_trigger_history_projection() -> None:
    """Reset the global projection (for testing)."""
    global _projection
    _projection = None
