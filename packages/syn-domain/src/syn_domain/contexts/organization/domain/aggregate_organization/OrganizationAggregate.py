"""Organization Aggregate.

Aggregate root for organizations.

Uses AggregateRoot pattern (ADR-007) with event sourcing decorators
for compatibility with EventStoreRepository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.CreateOrganizationCommand import (
        CreateOrganizationCommand,
    )
    from syn_domain.contexts.organization.domain.commands.DeleteOrganizationCommand import (
        DeleteOrganizationCommand,
    )
    from syn_domain.contexts.organization.domain.commands.UpdateOrganizationCommand import (
        UpdateOrganizationCommand,
    )
    from syn_domain.contexts.organization.domain.events.OrganizationCreatedEvent import (
        OrganizationCreatedEvent,
    )
    from syn_domain.contexts.organization.domain.events.OrganizationDeletedEvent import (
        OrganizationDeletedEvent,
    )
    from syn_domain.contexts.organization.domain.events.OrganizationUpdatedEvent import (
        OrganizationUpdatedEvent,
    )


@aggregate("Organization")
class OrganizationAggregate(AggregateRoot["OrganizationCreatedEvent"]):
    """Aggregate root for an organization."""

    _aggregate_type: str  # Set by @aggregate decorator

    def __init__(self) -> None:
        super().__init__()
        self._name: str = ""
        self._slug: str = ""
        self._created_by: str = ""
        self._created_at: str = ""
        self._is_deleted: bool = False

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # --- Property accessors ---

    @property
    def organization_id(self) -> str:
        return str(self.id) if self.id else ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def slug(self) -> str:
        return self._slug

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

    @command_handler("CreateOrganizationCommand")
    def create(self, command: CreateOrganizationCommand) -> None:
        from syn_domain.contexts.organization.domain.events.OrganizationCreatedEvent import (
            OrganizationCreatedEvent,
        )

        if self.id is not None:
            msg = "Organization already created"
            raise ValueError(msg)

        org_id = command.aggregate_id or f"org-{uuid4().hex[:8]}"
        self._initialize(org_id)

        event = OrganizationCreatedEvent(
            organization_id=org_id,
            name=command.name,
            slug=command.slug,
            created_by=command.created_by,
        )
        self._apply(event)

    @command_handler("UpdateOrganizationCommand")
    def update(self, command: UpdateOrganizationCommand) -> None:
        from syn_domain.contexts.organization.domain.events.OrganizationUpdatedEvent import (
            OrganizationUpdatedEvent,
        )

        if self.id is None:
            msg = "Organization does not exist"
            raise ValueError(msg)
        if self._is_deleted:
            msg = "Cannot update a deleted organization"
            raise ValueError(msg)

        event = OrganizationUpdatedEvent(
            organization_id=self.organization_id,
            name=command.name if command.name is not None and command.name != self._name else None,
            slug=command.slug if command.slug is not None and command.slug != self._slug else None,
        )
        self._apply(event)

    @command_handler("DeleteOrganizationCommand")
    def delete(self, command: DeleteOrganizationCommand) -> None:
        from syn_domain.contexts.organization.domain.events.OrganizationDeletedEvent import (
            OrganizationDeletedEvent,
        )

        if self._is_deleted:
            msg = "Organization already deleted"
            raise ValueError(msg)

        event = OrganizationDeletedEvent(
            organization_id=self.organization_id,
            deleted_by=command.deleted_by,
        )
        self._apply(event)

    # --- Event sourcing handlers ---

    @event_sourcing_handler("organization.OrganizationCreated")
    def on_organization_created(self, event: OrganizationCreatedEvent) -> None:
        if hasattr(event, "name"):
            self._name = event.name
            self._slug = event.slug
            self._created_by = event.created_by
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._name = data.get("name", "")
            self._slug = data.get("slug", "")
            self._created_by = data.get("created_by", "")
        self._is_deleted = False

    @staticmethod
    def _extract_optional_fields(
        event: OrganizationUpdatedEvent,
    ) -> tuple[str | None, str | None]:
        """Extract (name, slug) from typed or dict-based update event."""
        if hasattr(event, "name"):
            return event.name, event.slug
        data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        return data.get("name"), data.get("slug")

    @event_sourcing_handler("organization.OrganizationUpdated")
    def on_organization_updated(self, event: OrganizationUpdatedEvent) -> None:
        name, slug = self._extract_optional_fields(event)
        if name is not None:
            self._name = name
        if slug is not None:
            self._slug = slug

    @event_sourcing_handler("organization.OrganizationDeleted")
    def on_organization_deleted(self, _event: OrganizationDeletedEvent) -> None:
        self._is_deleted = True
