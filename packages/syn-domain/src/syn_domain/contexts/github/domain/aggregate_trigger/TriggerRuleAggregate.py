"""Trigger Rule Aggregate.

Aggregate root for GitHub webhook trigger rules.

Uses AggregateRoot pattern (ADR-007) with event sourcing decorators
for compatibility with EventStoreRepository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.domain.commands.RecordTriggerBlockedCommand import (
        RecordTriggerBlockedCommand,
    )
    from syn_domain.contexts.github.domain.commands.RecordTriggerFiredCommand import (
        RecordTriggerFiredCommand,
    )
    from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import (
        TriggerBlockedEvent,
    )
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


@aggregate("TriggerRule")
class TriggerRuleAggregate(AggregateRoot["TriggerRegisteredEvent"]):
    """Aggregate root for a webhook trigger rule."""

    _aggregate_type: str  # Set by @aggregate decorator

    def __init__(self) -> None:
        super().__init__()
        self._name: str = ""
        self._status: TriggerStatus = TriggerStatus.ACTIVE
        self._event: str = ""
        self._conditions: list[TriggerCondition] = []
        self._repository: str = ""
        self._installation_id: str = ""
        self._workflow_id: str = ""
        self._input_mapping: dict[str, str] = {}
        self._config: TriggerConfig = TriggerConfig()
        self._created_by: str = ""
        self._fire_count: int = 0

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # --- Property accessors ---

    @property
    def trigger_id(self) -> str:
        return str(self.id) if self.id else ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> TriggerStatus:
        return self._status

    @property
    def event(self) -> str:
        return self._event

    @property
    def conditions(self) -> list[TriggerCondition]:
        return list(self._conditions)

    @property
    def repository(self) -> str:
        return self._repository

    @property
    def installation_id(self) -> str:
        return self._installation_id

    @property
    def workflow_id(self) -> str:
        return self._workflow_id

    @property
    def input_mapping(self) -> dict[str, str]:
        return dict(self._input_mapping)

    @property
    def config(self) -> TriggerConfig:
        return self._config

    @property
    def created_by(self) -> str:
        return self._created_by

    @property
    def fire_count(self) -> int:
        return self._fire_count

    # --- Command handlers ---

    @command_handler("RegisterTriggerCommand")
    def register(self, command: Any) -> None:  # noqa: ANN401
        from syn_domain.contexts.github.domain.events.TriggerRegisteredEvent import (
            TriggerRegisteredEvent,
        )

        if self.id is not None:
            msg = "Trigger already registered"
            raise ValueError(msg)

        trigger_id = command.aggregate_id or f"tr-{uuid4().hex[:8]}"
        self._initialize(trigger_id)

        conditions_raw = command.conditions
        config_dict = dict(command.config) if command.config else {}
        input_mapping = dict(command.input_mapping) if command.input_mapping else {}

        event = TriggerRegisteredEvent(
            trigger_id=trigger_id,
            name=command.name,
            event=command.event,
            conditions=tuple(c if isinstance(c, dict) else dict(c) for c in conditions_raw),
            repository=command.repository,
            installation_id=command.installation_id,
            workflow_id=command.workflow_id,
            input_mapping=input_mapping,
            config=config_dict,
            created_by=command.created_by,
        )
        self._apply(event)

    @command_handler("PauseTriggerCommand")
    def pause(self, command: Any) -> None:  # noqa: ANN401
        from syn_domain.contexts.github.domain.events.TriggerPausedEvent import (
            TriggerPausedEvent,
        )

        if self._status != TriggerStatus.ACTIVE:
            msg = f"Cannot pause trigger in status {self._status}"
            raise ValueError(msg)

        event = TriggerPausedEvent(
            trigger_id=self.trigger_id,
            paused_by=command.paused_by,
            reason=command.reason,
        )
        self._apply(event)

    @command_handler("ResumeTriggerCommand")
    def resume(self, command: Any) -> None:  # noqa: ANN401
        from syn_domain.contexts.github.domain.events.TriggerResumedEvent import (
            TriggerResumedEvent,
        )

        if self._status != TriggerStatus.PAUSED:
            msg = f"Cannot resume trigger in status {self._status}"
            raise ValueError(msg)

        event = TriggerResumedEvent(
            trigger_id=self.trigger_id,
            resumed_by=command.resumed_by,
        )
        self._apply(event)

    @command_handler("DeleteTriggerCommand")
    def delete(self, command: Any) -> None:  # noqa: ANN401
        from syn_domain.contexts.github.domain.events.TriggerDeletedEvent import (
            TriggerDeletedEvent,
        )

        if self._status == TriggerStatus.DELETED:
            msg = "Trigger already deleted"
            raise ValueError(msg)

        event = TriggerDeletedEvent(
            trigger_id=self.trigger_id,
            deleted_by=command.deleted_by,
        )
        self._apply(event)

    @command_handler("RecordTriggerFiredCommand")
    def record_fired(self, command: RecordTriggerFiredCommand) -> None:
        from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
            TriggerFiredEvent,
        )

        event = TriggerFiredEvent(
            trigger_id=self.trigger_id,
            execution_id=command.execution_id,
            webhook_delivery_id=command.webhook_delivery_id,
            github_event_type=command.event_type,
            repository=command.repository,
            pr_number=command.pr_number,
            payload_summary=command.payload_summary or {},
            workflow_id=command.workflow_id,
            workflow_inputs=command.workflow_inputs or {},
        )
        self._apply(event)

    @command_handler("RecordTriggerBlockedCommand")
    def record_blocked(self, command: RecordTriggerBlockedCommand) -> None:
        from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import (
            TriggerBlockedEvent,
        )

        event = TriggerBlockedEvent(
            trigger_id=self.trigger_id,
            guard_name=command.guard_name,
            reason=command.reason,
            webhook_delivery_id=command.webhook_delivery_id,
            github_event_type=command.event_type,
            repository=command.repository,
            pr_number=command.pr_number,
            payload_summary=command.payload_summary or {},
        )
        self._apply(event)

    def can_fire(self) -> bool:
        """Check if this trigger is in a state that allows firing."""
        return self._status == TriggerStatus.ACTIVE

    # --- Event sourcing handlers ---

    @staticmethod
    def _extract_trigger_fields(
        event: TriggerRegisteredEvent,
    ) -> tuple[str, str, str, str, str, str, dict[str, str], Any, Any]:
        """Extract core trigger fields from a typed or dict-based event.

        Returns (name, event_type, repository, installation_id, workflow_id,
                 created_by, input_mapping, conditions_raw, config_raw).
        """
        if hasattr(event, "name"):
            return (
                event.name,
                event.event,
                event.repository,
                event.installation_id,
                event.workflow_id,
                event.created_by,
                dict(event.input_mapping) if event.input_mapping else {},
                event.conditions,
                event.config,
            )
        data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        return (
            data.get("name", ""),
            data.get("event", ""),
            data.get("repository", ""),
            data.get("installation_id", ""),
            data.get("workflow_id", ""),
            data.get("created_by", ""),
            data.get("input_mapping", {}),
            data.get("conditions", ()),
            data.get("config", {}),
        )

    @staticmethod
    def _parse_trigger_config(config_raw: Any) -> TriggerConfig:  # noqa: ANN401
        """Parse a config dict into a TriggerConfig, ignoring unknown keys."""
        config_dict = config_raw if isinstance(config_raw, dict) else {}
        if not config_dict:
            return TriggerConfig()
        valid_keys = set(TriggerConfig.__dataclass_fields__)
        return TriggerConfig(**{k: v for k, v in config_dict.items() if k in valid_keys})

    @event_sourcing_handler("github.TriggerRegistered")
    def on_trigger_registered(self, event: TriggerRegisteredEvent) -> None:
        (
            self._name,
            self._event,
            self._repository,
            self._installation_id,
            self._workflow_id,
            self._created_by,
            self._input_mapping,
            conditions_raw,
            config_raw,
        ) = self._extract_trigger_fields(event)

        self._conditions = [
            TriggerCondition(
                field=c.get("field", ""),
                operator=c.get("operator", "eq"),
                value=c.get("value"),
            )
            for c in conditions_raw
        ]
        self._config = self._parse_trigger_config(config_raw)
        self._status = TriggerStatus.ACTIVE

    @event_sourcing_handler("github.TriggerPaused")
    def on_trigger_paused(self, _event: TriggerPausedEvent) -> None:
        self._status = TriggerStatus.PAUSED

    @event_sourcing_handler("github.TriggerResumed")
    def on_trigger_resumed(self, _event: TriggerResumedEvent) -> None:
        self._status = TriggerStatus.ACTIVE

    @event_sourcing_handler("github.TriggerDeleted")
    def on_trigger_deleted(self, _event: TriggerDeletedEvent) -> None:
        self._status = TriggerStatus.DELETED

    @event_sourcing_handler("github.TriggerFired")
    def on_trigger_fired(self, _event: TriggerFiredEvent) -> None:
        self._fire_count += 1

    @event_sourcing_handler("github.TriggerBlocked")
    def on_trigger_blocked(self, _event: TriggerBlockedEvent) -> None:
        pass  # Audit-only event — no aggregate state change
