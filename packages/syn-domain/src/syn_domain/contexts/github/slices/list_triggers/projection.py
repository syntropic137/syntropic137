"""Trigger rule projection.

Projects trigger events into TriggerRule read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from syn_domain.contexts.github.domain.read_models.trigger_rule import TriggerRule

if TYPE_CHECKING:
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


class TriggerRuleProjection:
    """Projects trigger events into TriggerRule read models.

    Maintains an in-memory cache of trigger rules for fast lookups.
    """

    def __init__(self) -> None:
        """Initialize the projection."""
        self._rules: dict[str, TriggerRule] = {}

    def handle_trigger_registered(self, event: TriggerRegisteredEvent) -> TriggerRule:
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
        self._rules[event.trigger_id] = rule
        logger.info(f"Projected TriggerRegistered: {event.trigger_id} ({event.name})")
        return rule

    def handle_trigger_paused(self, event: TriggerPausedEvent) -> TriggerRule | None:
        """Handle a TriggerPaused event."""
        rule = self._rules.get(event.trigger_id)
        if rule is None:
            logger.warning(f"TriggerPaused for unknown trigger: {event.trigger_id}")
            return None
        rule.status = TriggerStatus.PAUSED
        logger.info(f"Projected TriggerPaused: {event.trigger_id}")
        return rule

    def handle_trigger_resumed(self, event: TriggerResumedEvent) -> TriggerRule | None:
        """Handle a TriggerResumed event."""
        rule = self._rules.get(event.trigger_id)
        if rule is None:
            logger.warning(f"TriggerResumed for unknown trigger: {event.trigger_id}")
            return None
        rule.status = TriggerStatus.ACTIVE
        logger.info(f"Projected TriggerResumed: {event.trigger_id}")
        return rule

    def handle_trigger_deleted(self, event: TriggerDeletedEvent) -> TriggerRule | None:
        """Handle a TriggerDeleted event."""
        rule = self._rules.get(event.trigger_id)
        if rule is None:
            logger.warning(f"TriggerDeleted for unknown trigger: {event.trigger_id}")
            return None
        rule.status = TriggerStatus.DELETED
        logger.info(f"Projected TriggerDeleted: {event.trigger_id}")
        return rule

    def handle_trigger_fired(self, event: TriggerFiredEvent) -> TriggerRule | None:
        """Handle a TriggerFired event."""
        rule = self._rules.get(event.trigger_id)
        if rule is None:
            logger.warning(f"TriggerFired for unknown trigger: {event.trigger_id}")
            return None
        rule.fire_count += 1
        rule.last_fired_at = datetime.now(UTC)
        return rule

    def get(self, trigger_id: str) -> TriggerRule | None:
        """Get a trigger rule by ID."""
        return self._rules.get(trigger_id)

    def list_all(
        self,
        repository: str | None = None,
        status: str | None = None,
    ) -> list[TriggerRule]:
        """List trigger rules with optional filters."""
        results = list(self._rules.values())
        if repository:
            results = [r for r in results if r.repository == repository]
        if status:
            results = [r for r in results if r.status.value == status]
        return results


# Singleton
_projection: TriggerRuleProjection | None = None


def get_trigger_rule_projection() -> TriggerRuleProjection:
    """Get the global trigger rule projection instance."""
    global _projection
    if _projection is None:
        _projection = TriggerRuleProjection()
    return _projection


def reset_trigger_rule_projection() -> None:
    """Reset the global projection (for testing)."""
    global _projection
    _projection = None
