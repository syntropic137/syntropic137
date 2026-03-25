"""System Aggregate.

Aggregate root for systems.

Uses AggregateRoot pattern (ADR-007) with event sourcing decorators
for compatibility with EventStoreRepository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import (
        SystemCreatedEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemDeletedEvent import (
        SystemDeletedEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemUpdatedEvent import (
        SystemUpdatedEvent,
    )


@aggregate("System")
class SystemAggregate(AggregateRoot["SystemCreatedEvent"]):
    """Aggregate root for a system."""

    _aggregate_type: str  # Set by @aggregate decorator

    def __init__(self) -> None:
        super().__init__()
        self._organization_id: str = ""
        self._name: str = ""
        self._description: str = ""
        self._created_by: str = ""
        self._created_at: str = ""
        self._is_deleted: bool = False

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # --- Property accessors ---

    @property
    def system_id(self) -> str:
        return str(self.id) if self.id else ""

    @property
    def organization_id(self) -> str:
        return self._organization_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def created_by(self) -> str:
        return self._created_by

    @property
    def created_at(self) -> str:
        return self._created_at

    @property
    def is_deleted(self) -> bool:
        return self._is_deleted

    # --- Command handlers ---

    @command_handler("CreateSystemCommand")
    def create(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import (
            SystemCreatedEvent,
        )

        if self.id is not None:
            msg = "System already created"
            raise ValueError(msg)

        system_id = command.aggregate_id or f"sys-{uuid4().hex[:8]}"
        self._initialize(system_id)

        event = SystemCreatedEvent(
            system_id=system_id,
            organization_id=command.organization_id,
            name=command.name,
            description=command.description,
            created_by=command.created_by,
        )
        self._apply(event)

    @command_handler("UpdateSystemCommand")
    def update(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.SystemUpdatedEvent import (
            SystemUpdatedEvent,
        )

        if self.id is None:
            msg = "System does not exist"
            raise ValueError(msg)
        if self._is_deleted:
            msg = "Cannot update a deleted system"
            raise ValueError(msg)

        event = SystemUpdatedEvent(
            system_id=self.system_id,
            name=command.name if command.name is not None and command.name != self._name else None,
            description=command.description
            if command.description is not None and command.description != self._description
            else None,
        )
        self._apply(event)

    @command_handler("DeleteSystemCommand")
    def delete(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.SystemDeletedEvent import (
            SystemDeletedEvent,
        )

        if self._is_deleted:
            msg = "System already deleted"
            raise ValueError(msg)

        event = SystemDeletedEvent(
            system_id=self.system_id,
            deleted_by=command.deleted_by,
        )
        self._apply(event)

    # --- Event sourcing handlers ---

    @event_sourcing_handler("organization.SystemCreated")
    def on_system_created(self, event: SystemCreatedEvent) -> None:
        if hasattr(event, "name"):
            self._organization_id = event.organization_id
            self._name = event.name
            self._description = event.description
            self._created_by = event.created_by
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._organization_id = data.get("organization_id", "")
            self._name = data.get("name", "")
            self._description = data.get("description", "")
            self._created_by = data.get("created_by", "")
        self._is_deleted = False

    @staticmethod
    def _extract_optional_fields(
        event: SystemUpdatedEvent,
    ) -> tuple[str | None, str | None]:
        """Extract (name, description) from typed or dict-based update event."""
        if hasattr(event, "name"):
            return event.name, event.description
        data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        return data.get("name"), data.get("description")

    @event_sourcing_handler("organization.SystemUpdated")
    def on_system_updated(self, event: SystemUpdatedEvent) -> None:
        name, description = self._extract_optional_fields(event)
        if name is not None:
            self._name = name
        if description is not None:
            self._description = description

    @event_sourcing_handler("organization.SystemDeleted")
    def on_system_deleted(self, _event: SystemDeletedEvent) -> None:
        self._is_deleted = True
