"""Repo Aggregate.

Aggregate root for repositories.

Uses AggregateRoot pattern (ADR-007) with event sourcing decorators
for compatibility with EventStoreRepository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
        RepoAssignedToSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoDeregisteredEvent import (
        RepoDeregisteredEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
        RepoRegisteredEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoUnassignedFromSystemEvent import (
        RepoUnassignedFromSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoUpdatedEvent import (
        RepoUpdatedEvent,
    )


@aggregate("Repo")
class RepoAggregate(AggregateRoot["RepoRegisteredEvent"]):
    """Aggregate root for a repository."""

    _aggregate_type: str  # Set by @aggregate decorator

    def __init__(self) -> None:
        super().__init__()
        self._organization_id: str = ""
        self._system_id: str = ""  # empty string = unassigned
        self._provider: str = ""  # github/gitea/gitlab
        self._provider_repo_id: str = ""
        self._full_name: str = ""
        self._owner: str = ""
        self._default_branch: str = "main"
        self._installation_id: str = ""
        self._is_private: bool = False
        self._is_deregistered: bool = False
        self._created_at: str = ""

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # --- Property accessors ---

    @property
    def repo_id(self) -> str:
        return str(self.id) if self.id else ""

    @property
    def organization_id(self) -> str:
        return self._organization_id

    @property
    def system_id(self) -> str:
        return self._system_id

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def provider_repo_id(self) -> str:
        return self._provider_repo_id

    @property
    def full_name(self) -> str:
        return self._full_name

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def default_branch(self) -> str:
        return self._default_branch

    @property
    def installation_id(self) -> str:
        return self._installation_id

    @property
    def is_private(self) -> bool:
        return self._is_private

    @property
    def is_deregistered(self) -> bool:
        return self._is_deregistered

    @property
    def created_at(self) -> str:
        return self._created_at

    # --- Command handlers ---

    @command_handler("RegisterRepoCommand")
    def register(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
            RepoRegisteredEvent,
        )

        if self.id is not None:
            msg = "Repo already registered"
            raise ValueError(msg)

        repo_id = command.aggregate_id if command.aggregate_id else f"repo-{uuid4().hex[:8]}"
        self._initialize(repo_id)

        event = RepoRegisteredEvent(
            repo_id=repo_id,
            organization_id=command.organization_id,
            provider=command.provider,
            provider_repo_id=command.provider_repo_id,
            full_name=command.full_name,
            owner=command.owner,
            default_branch=command.default_branch,
            installation_id=command.installation_id,
            is_private=command.is_private,
            created_by=command.created_by,
        )
        self._apply(event)

    @command_handler("AssignRepoToSystemCommand")
    def assign_to_system(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
            RepoAssignedToSystemEvent,
        )

        if self.id is None:
            msg = "Repo does not exist"
            raise ValueError(msg)
        if self._is_deregistered:
            msg = "Repo is deregistered"
            raise ValueError(msg)
        if self._system_id:
            msg = "Repo is already assigned to a system"
            raise ValueError(msg)

        event = RepoAssignedToSystemEvent(
            repo_id=self.repo_id,
            system_id=command.system_id,
        )
        self._apply(event)

    @command_handler("UnassignRepoFromSystemCommand")
    def unassign_from_system(self, command: Any) -> None:  # noqa: ARG002
        from syn_domain.contexts.organization.domain.events.RepoUnassignedFromSystemEvent import (
            RepoUnassignedFromSystemEvent,
        )

        if self.id is None:
            msg = "Repo does not exist"
            raise ValueError(msg)
        if self._is_deregistered:
            msg = "Repo is deregistered"
            raise ValueError(msg)
        if not self._system_id:
            msg = "Repo is not assigned to any system"
            raise ValueError(msg)

        event = RepoUnassignedFromSystemEvent(
            repo_id=self.repo_id,
            previous_system_id=self._system_id,
        )
        self._apply(event)

    @command_handler("UpdateRepoCommand")
    def update(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.RepoUpdatedEvent import (
            RepoUpdatedEvent,
        )

        if self.id is None:
            msg = "Repo does not exist"
            raise ValueError(msg)
        if self._is_deregistered:
            msg = "Repo is deregistered"
            raise ValueError(msg)

        # Only include fields that actually changed
        default_branch = (
            command.default_branch
            if command.default_branch is not None and command.default_branch != self._default_branch
            else None
        )
        is_private = (
            command.is_private
            if command.is_private is not None and command.is_private != self._is_private
            else None
        )
        installation_id = (
            command.installation_id
            if command.installation_id is not None
            and command.installation_id != self._installation_id
            else None
        )

        # If nothing actually changed, no-op
        if default_branch is None and is_private is None and installation_id is None:
            return

        event = RepoUpdatedEvent(
            repo_id=self.repo_id,
            default_branch=default_branch,
            is_private=is_private,
            installation_id=installation_id,
            updated_by=command.updated_by,
        )
        self._apply(event)

    @command_handler("DeregisterRepoCommand")
    def deregister(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.RepoDeregisteredEvent import (
            RepoDeregisteredEvent,
        )

        if self.id is None:
            msg = "Repo does not exist"
            raise ValueError(msg)
        if self._is_deregistered:
            msg = "Repo is already deregistered"
            raise ValueError(msg)

        event = RepoDeregisteredEvent(
            repo_id=self.repo_id,
            organization_id=self._organization_id,
            system_id=self._system_id,
            deregistered_by=command.deregistered_by,
        )
        self._apply(event)

    # --- Event sourcing handlers ---

    @event_sourcing_handler("organization.RepoRegistered")
    def on_repo_registered(self, event: RepoRegisteredEvent) -> None:
        if hasattr(event, "organization_id"):
            self._organization_id = event.organization_id
            self._provider = event.provider
            self._provider_repo_id = event.provider_repo_id
            self._full_name = event.full_name
            self._owner = event.owner
            self._default_branch = event.default_branch
            self._installation_id = event.installation_id
            self._is_private = event.is_private
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._organization_id = data.get("organization_id", "")
            self._provider = data.get("provider", "")
            self._provider_repo_id = data.get("provider_repo_id", "")
            self._full_name = data.get("full_name", "")
            self._owner = data.get("owner", "")
            self._default_branch = data.get("default_branch", "main")
            self._installation_id = data.get("installation_id", "")
            self._is_private = data.get("is_private", False)
        self._system_id = ""

    @event_sourcing_handler("organization.RepoAssignedToSystem")
    def on_repo_assigned_to_system(self, event: RepoAssignedToSystemEvent) -> None:
        if hasattr(event, "system_id"):
            self._system_id = event.system_id
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._system_id = data.get("system_id", "")

    @event_sourcing_handler("organization.RepoUnassignedFromSystem")
    def on_repo_unassigned_from_system(self, _event: RepoUnassignedFromSystemEvent) -> None:
        self._system_id = ""

    @event_sourcing_handler("organization.RepoUpdated")
    def on_repo_updated(self, event: RepoUpdatedEvent) -> None:
        if hasattr(event, "default_branch") and event.default_branch is not None:
            self._default_branch = event.default_branch
        if hasattr(event, "is_private") and event.is_private is not None:
            self._is_private = event.is_private
        if hasattr(event, "installation_id") and event.installation_id is not None:
            self._installation_id = event.installation_id

    @event_sourcing_handler("organization.RepoDeregistered")
    def on_repo_deregistered(self, _event: RepoDeregisteredEvent) -> None:
        self._is_deregistered = True
