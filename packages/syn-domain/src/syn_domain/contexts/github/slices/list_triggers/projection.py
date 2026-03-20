"""Trigger rule projection.

Projects trigger events into TriggerRule read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from syn_domain.contexts.github.domain.read_models.trigger_rule import TriggerRule

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_domain.contexts.github.domain.events.TriggerDeletedEvent import (
        TriggerDeletedEvent,
    )
    from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
        TriggerFiredEvent,
    )
    from syn_domain.contexts.github.domain.events.TriggerPausedEvent import (
        TriggerPausedEvent,
    )
    from syn_domain.contexts.github.domain.events.TriggerRegisteredEvent import (
        TriggerRegisteredEvent,
    )
    from syn_domain.contexts.github.domain.events.TriggerResumedEvent import (
        TriggerResumedEvent,
    )

logger = logging.getLogger(__name__)

PROJECTION_NAME = "trigger_rules"


def _rule_to_dict(rule: TriggerRule) -> dict[str, Any]:
    return {
        "trigger_id": rule.trigger_id,
        "name": rule.name,
        "event": rule.event,
        "conditions": rule.conditions,
        "repository": rule.repository,
        "installation_id": rule.installation_id,
        "workflow_id": rule.workflow_id,
        "input_mapping": rule.input_mapping,
        "config": rule.config,
        "status": rule.status.value,
        "fire_count": rule.fire_count,
        "last_fired_at": rule.last_fired_at.isoformat() if rule.last_fired_at else None,
        "created_by": rule.created_by,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


def _rule_from_dict(data: dict[str, Any]) -> TriggerRule:
    return TriggerRule(
        trigger_id=data["trigger_id"],
        name=data["name"],
        event=data.get("event", ""),
        conditions=data.get("conditions", []),
        repository=data.get("repository", ""),
        installation_id=data.get("installation_id", ""),
        workflow_id=data.get("workflow_id", ""),
        input_mapping=data.get("input_mapping", {}),
        config=data.get("config", {}),
        status=TriggerStatus(data["status"]),
        fire_count=data.get("fire_count", 0),
        last_fired_at=datetime.fromisoformat(data["last_fired_at"])
        if data.get("last_fired_at")
        else None,
        created_by=data.get("created_by", ""),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
    )


class TriggerRuleProjection:
    """Projects trigger events into TriggerRule read models."""

    def __init__(self, store: ProjectionStoreProtocol) -> None:
        """Initialize the projection."""
        self._store = store

    async def handle_trigger_registered(self, event: TriggerRegisteredEvent) -> TriggerRule:
        """Handle a TriggerRegistered event."""
        rule = TriggerRule(
            trigger_id=event.trigger_id,
            name=event.name,
            event=event.event,
            conditions=list(event.conditions),
            repository=event.repository,
            installation_id=event.installation_id,
            workflow_id=event.workflow_id,
            input_mapping=dict(event.input_mapping),
            config=dict(event.config),
            status=TriggerStatus.ACTIVE,
            created_by=event.created_by,
            created_at=datetime.now(UTC),
        )
        await self._store.save(PROJECTION_NAME, event.trigger_id, _rule_to_dict(rule))
        logger.info(f"Projected TriggerRegistered: {event.trigger_id} ({event.name})")
        return rule

    async def handle_trigger_paused(self, event: TriggerPausedEvent) -> TriggerRule | None:
        """Handle a TriggerPaused event."""
        data = await self._store.get(PROJECTION_NAME, event.trigger_id)
        if data is None:
            logger.warning(f"TriggerPaused for unknown trigger: {event.trigger_id}")
            return None
        data["status"] = TriggerStatus.PAUSED.value
        await self._store.save(PROJECTION_NAME, event.trigger_id, data)
        logger.info(f"Projected TriggerPaused: {event.trigger_id}")
        return _rule_from_dict(data)

    async def handle_trigger_resumed(self, event: TriggerResumedEvent) -> TriggerRule | None:
        """Handle a TriggerResumed event."""
        data = await self._store.get(PROJECTION_NAME, event.trigger_id)
        if data is None:
            logger.warning(f"TriggerResumed for unknown trigger: {event.trigger_id}")
            return None
        data["status"] = TriggerStatus.ACTIVE.value
        await self._store.save(PROJECTION_NAME, event.trigger_id, data)
        logger.info(f"Projected TriggerResumed: {event.trigger_id}")
        return _rule_from_dict(data)

    async def handle_trigger_deleted(self, event: TriggerDeletedEvent) -> TriggerRule | None:
        """Handle a TriggerDeleted event."""
        data = await self._store.get(PROJECTION_NAME, event.trigger_id)
        if data is None:
            logger.warning(f"TriggerDeleted for unknown trigger: {event.trigger_id}")
            return None
        data["status"] = TriggerStatus.DELETED.value
        await self._store.save(PROJECTION_NAME, event.trigger_id, data)
        logger.info(f"Projected TriggerDeleted: {event.trigger_id}")
        return _rule_from_dict(data)

    async def handle_trigger_fired(self, event: TriggerFiredEvent) -> TriggerRule | None:
        """Handle a TriggerFired event."""
        data = await self._store.get(PROJECTION_NAME, event.trigger_id)
        if data is None:
            logger.warning(f"TriggerFired for unknown trigger: {event.trigger_id}")
            return None
        data["fire_count"] = data.get("fire_count", 0) + 1
        data["last_fired_at"] = datetime.now(UTC).isoformat()
        await self._store.save(PROJECTION_NAME, event.trigger_id, data)
        return _rule_from_dict(data)

    async def get(self, trigger_id: str) -> TriggerRule | None:
        """Get a trigger rule by ID."""
        data = await self._store.get(PROJECTION_NAME, trigger_id)
        return _rule_from_dict(data) if data else None

    async def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[TriggerRule]:
        """List trigger rules with optional filters."""
        records = await self._store.get_all(PROJECTION_NAME)
        results = [_rule_from_dict(r) for r in records]
        if repository:
            results = [r for r in results if r.repository == repository]
        if status:
            results = [r for r in results if r.status.value == status]
        return results

    async def clear_all_data(self) -> None:
        """Clear all projection data (for rebuild)."""
        records = await self._store.get_all(PROJECTION_NAME)
        for record in records:
            trigger_id = record.get("trigger_id")
            if trigger_id:
                await self._store.delete(PROJECTION_NAME, trigger_id)


# Singleton
_projection: TriggerRuleProjection | None = None


def get_trigger_rule_projection() -> TriggerRuleProjection:
    """Get the global trigger rule projection instance."""
    global _projection
    if _projection is None:
        from syn_adapters.projection_stores import get_projection_store

        _projection = TriggerRuleProjection(store=get_projection_store())
    return _projection


def reset_trigger_rule_projection() -> None:
    """Reset the global projection (for testing)."""
    global _projection
    _projection = None
