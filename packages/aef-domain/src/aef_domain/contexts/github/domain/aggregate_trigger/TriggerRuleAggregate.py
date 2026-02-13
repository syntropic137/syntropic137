"""Trigger Rule Aggregate.

Aggregate root for GitHub webhook trigger rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from aef_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)
from aef_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from aef_domain.contexts.github.domain.events.TriggerDeletedEvent import (
    TriggerDeletedEvent,
)
from aef_domain.contexts.github.domain.events.TriggerFiredEvent import (
    TriggerFiredEvent,
)
from aef_domain.contexts.github.domain.events.TriggerPausedEvent import (
    TriggerPausedEvent,
)
from aef_domain.contexts.github.domain.events.TriggerRegisteredEvent import (
    TriggerRegisteredEvent,
)
from aef_domain.contexts.github.domain.events.TriggerResumedEvent import (
    TriggerResumedEvent,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )


@dataclass
class TriggerRuleAggregate:
    """Aggregate root for a webhook trigger rule.

    Manages the lifecycle of a trigger rule that maps
    GitHub webhook events to workflow executions.

    States: active -> paused -> active (toggle)
                   -> deleted (terminal)

    Attributes:
        trigger_id: Unique identifier for this trigger rule.
        name: Human-readable name.
        status: Current lifecycle status.
        event: GitHub event type (e.g. "check_run.completed").
        conditions: Conditions that must all be true for the trigger to fire.
        repository: Target repository (owner/repo).
        installation_id: GitHub App installation ID.
        workflow_id: Workflow to dispatch when trigger fires.
        input_mapping: Map of workflow input names to payload paths.
        config: Safety configuration.
        created_by: User or agent that registered.
        fire_count: Total number of times this trigger has fired.
        pending_events: Events that have been applied but not persisted.
    """

    trigger_id: str
    name: str = ""
    status: TriggerStatus = TriggerStatus.ACTIVE
    event: str = ""
    conditions: list[TriggerCondition] = field(default_factory=list)
    repository: str = ""
    installation_id: str = ""
    workflow_id: str = ""
    input_mapping: dict[str, str] = field(default_factory=dict)
    config: TriggerConfig = field(default_factory=TriggerConfig)
    created_by: str = ""
    fire_count: int = 0
    pending_events: list = field(default_factory=list)

    @classmethod
    def register(cls, cmd: RegisterTriggerCommand) -> TriggerRuleAggregate:
        """Create a new trigger rule from a command.

        Args:
            cmd: The RegisterTriggerCommand with trigger details.

        Returns:
            New TriggerRuleAggregate with TriggerRegisteredEvent.
        """
        trigger_id = f"tr-{uuid4().hex[:8]}"

        conditions = [
            TriggerCondition(
                field=c.get("field", ""),
                operator=c.get("operator", "eq"),
                value=c.get("value"),
            )
            for c in cmd.conditions
        ]

        config_dict = dict(cmd.config) if cmd.config else {}
        config = TriggerConfig(
            max_attempts=cast("int", config_dict.get("max_attempts", 3)),
            budget_per_trigger_usd=cast("float", config_dict.get("budget_per_trigger_usd", 5.00)),
            daily_limit=cast("int", config_dict.get("daily_limit", 20)),
            debounce_seconds=cast("int", config_dict.get("debounce_seconds", 0)),
            cooldown_seconds=cast("int", config_dict.get("cooldown_seconds", 300)),
            skip_if_sender_is_bot=cast("bool", config_dict.get("skip_if_sender_is_bot", True)),
        )

        input_mapping = dict(cmd.input_mapping) if cmd.input_mapping else {}

        aggregate = cls(
            trigger_id=trigger_id,
            name=cmd.name,
            status=TriggerStatus.ACTIVE,
            event=cmd.event,
            conditions=conditions,
            repository=cmd.repository,
            installation_id=cmd.installation_id,
            workflow_id=cmd.workflow_id,
            input_mapping=input_mapping,
            config=config,
            created_by=cmd.created_by,
        )

        event = TriggerRegisteredEvent(
            trigger_id=trigger_id,
            name=cmd.name,
            event=cmd.event,
            conditions=tuple(dict(c) for c in cmd.conditions),
            repository=cmd.repository,
            installation_id=cmd.installation_id,
            workflow_id=cmd.workflow_id,
            input_mapping=input_mapping,
            config=config_dict,
            created_by=cmd.created_by,
        )

        aggregate.pending_events.append(event)
        return aggregate

    def pause(self, paused_by: str, reason: str | None = None) -> TriggerPausedEvent | None:
        """Pause this trigger (stop firing, keep config).

        Args:
            paused_by: User or agent pausing the trigger.
            reason: Optional reason for pausing.

        Returns:
            TriggerPausedEvent if trigger was active, None otherwise.
        """
        if self.status != TriggerStatus.ACTIVE:
            return None

        self.status = TriggerStatus.PAUSED

        event = TriggerPausedEvent(
            trigger_id=self.trigger_id,
            paused_by=paused_by,
            reason=reason,
        )

        self.pending_events.append(event)
        return event

    def resume(self, resumed_by: str) -> TriggerResumedEvent | None:
        """Resume a paused trigger.

        Args:
            resumed_by: User or agent resuming the trigger.

        Returns:
            TriggerResumedEvent if trigger was paused, None otherwise.
        """
        if self.status != TriggerStatus.PAUSED:
            return None

        self.status = TriggerStatus.ACTIVE

        event = TriggerResumedEvent(
            trigger_id=self.trigger_id,
            resumed_by=resumed_by,
        )

        self.pending_events.append(event)
        return event

    def delete(self, deleted_by: str) -> TriggerDeletedEvent | None:
        """Soft-delete this trigger.

        Args:
            deleted_by: User or agent deleting the trigger.

        Returns:
            TriggerDeletedEvent if trigger was not already deleted, None otherwise.
        """
        if self.status == TriggerStatus.DELETED:
            return None

        self.status = TriggerStatus.DELETED

        event = TriggerDeletedEvent(
            trigger_id=self.trigger_id,
            deleted_by=deleted_by,
        )

        self.pending_events.append(event)
        return event

    def record_fired(
        self,
        execution_id: str,
        webhook_delivery_id: str,
        event_type: str,
        repository: str,
        pr_number: int | None = None,
        payload_summary: dict | None = None,
    ) -> TriggerFiredEvent:
        """Record that this trigger fired and started an execution.

        Args:
            execution_id: ID of the dispatched workflow execution.
            webhook_delivery_id: X-GitHub-Delivery header.
            event_type: GitHub event type.
            repository: Repository that received the webhook.
            pr_number: PR number if applicable.
            payload_summary: Key fields from the webhook payload.

        Returns:
            TriggerFiredEvent.
        """
        self.fire_count += 1

        event = TriggerFiredEvent(
            trigger_id=self.trigger_id,
            execution_id=execution_id,
            webhook_delivery_id=webhook_delivery_id,
            github_event_type=event_type,
            repository=repository,
            pr_number=pr_number,
            payload_summary=payload_summary or {},
        )

        self.pending_events.append(event)
        return event

    def can_fire(self) -> bool:
        """Check if this trigger is in a state that allows firing."""
        return self.status == TriggerStatus.ACTIVE

    def clear_pending_events(self) -> list:
        """Clear and return pending events.

        Used after events have been persisted.

        Returns:
            List of pending events that were cleared.
        """
        events = self.pending_events[:]
        self.pending_events = []
        return events

    @classmethod
    def from_events(cls, events: list) -> TriggerRuleAggregate | None:
        """Reconstitute aggregate from event history.

        Args:
            events: List of domain events in order.

        Returns:
            TriggerRuleAggregate with state from events, or None if no events.
        """
        if not events:
            return None

        aggregate = None

        for evt in events:
            if isinstance(evt, TriggerRegisteredEvent):
                conditions = [
                    TriggerCondition(
                        field=c.get("field", ""),
                        operator=c.get("operator", "eq"),
                        value=c.get("value"),
                    )
                    for c in evt.conditions
                ]
                config = TriggerConfig(**evt.config) if evt.config else TriggerConfig()
                aggregate = cls(
                    trigger_id=evt.trigger_id,
                    name=evt.name,
                    status=TriggerStatus.ACTIVE,
                    event=evt.event,
                    conditions=conditions,
                    repository=evt.repository,
                    installation_id=evt.installation_id,
                    workflow_id=evt.workflow_id,
                    input_mapping=dict(evt.input_mapping),
                    config=config,
                    created_by=evt.created_by,
                )
            elif aggregate and isinstance(evt, TriggerPausedEvent):
                aggregate.status = TriggerStatus.PAUSED
            elif aggregate and isinstance(evt, TriggerResumedEvent):
                aggregate.status = TriggerStatus.ACTIVE
            elif aggregate and isinstance(evt, TriggerDeletedEvent):
                aggregate.status = TriggerStatus.DELETED
            elif aggregate and isinstance(evt, TriggerFiredEvent):
                aggregate.fire_count += 1

        return aggregate
