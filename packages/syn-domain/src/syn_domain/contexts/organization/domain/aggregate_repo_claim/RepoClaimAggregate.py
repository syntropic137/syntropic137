"""Repo Claim aggregate — enforces repo uniqueness per (org, provider, full_name).

Uses the stream-per-unique-value pattern: the aggregate ID is a
deterministic hash of the uniqueness key, so the event store's
``ExpectedVersion.NO_STREAM`` semantics prevent duplicate creation.

See ADR-021 in the event-sourcing-platform for pattern documentation.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler


@aggregate("RepoClaim")
class RepoClaimAggregate(AggregateRoot["RepoClaimedEvent"]):  # type: ignore[type-arg]
    """Lightweight aggregate that claims a (org, provider, full_name) tuple.

    Lifecycle:
        1. ``claim()`` — first registration, or re-registration after release
        2. ``release()`` — when the repo is deregistered
    """

    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._organization_id: str = ""
        self._provider: str = ""
        self._full_name: str = ""
        self._repo_id: str = ""
        self._is_released: bool = False

    # --- Properties ---

    @property
    def organization_id(self) -> str:
        return self._organization_id

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def full_name(self) -> str:
        return self._full_name

    @property
    def repo_id(self) -> str:
        return self._repo_id

    @property
    def is_released(self) -> bool:
        return self._is_released

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # --- Command handlers ---

    @command_handler("ClaimRepoCommand")
    def claim(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.RepoClaimedEvent import (
            RepoClaimedEvent,
        )

        if self.id is not None and not self._is_released:
            msg = "Repo is already claimed"
            raise ValueError(msg)

        if self._is_released:
            # Re-claim after release (re-registration after deregister)
            event = RepoClaimedEvent(
                claim_id=str(self.id),
                organization_id=command.organization_id,
                provider=command.provider,
                full_name=command.full_name,
                repo_id=command.repo_id,
            )
            self._apply(event)
            return

        # First-time claim
        self._initialize(command.aggregate_id)
        event = RepoClaimedEvent(
            claim_id=command.aggregate_id,
            organization_id=command.organization_id,
            provider=command.provider,
            full_name=command.full_name,
            repo_id=command.repo_id,
        )
        self._apply(event)

    @command_handler("ReleaseRepoClaimCommand")
    def release(self, command: Any) -> None:
        from syn_domain.contexts.organization.domain.events.RepoClaimReleasedEvent import (
            RepoClaimReleasedEvent,
        )

        if self.id is None:
            msg = "Claim does not exist"
            raise ValueError(msg)
        if self._is_released:
            msg = "Claim is already released"
            raise ValueError(msg)
        if command.claim_id != str(self.id):
            msg = f"claim_id mismatch: expected '{self.id}', got '{command.claim_id}'"
            raise ValueError(msg)
        if command.repo_id != self._repo_id:
            msg = f"repo_id mismatch: expected '{self._repo_id}', got '{command.repo_id}'"
            raise ValueError(msg)

        event = RepoClaimReleasedEvent(
            claim_id=str(self.id),
            repo_id=self._repo_id,
        )
        self._apply(event)

    # --- Event sourcing handlers ---

    @event_sourcing_handler("organization.RepoClaimed")
    def on_claimed(self, event: Any) -> None:
        if hasattr(event, "organization_id"):
            self._organization_id = event.organization_id
            self._provider = event.provider
            self._full_name = event.full_name
            self._repo_id = event.repo_id
        else:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._organization_id = data.get("organization_id", "")
            self._provider = data.get("provider", "")
            self._full_name = data.get("full_name", "")
            self._repo_id = data.get("repo_id", "")
        self._is_released = False

    @event_sourcing_handler("organization.RepoClaimReleased")
    def on_released(self, event: Any) -> None:  # noqa: ARG002
        self._is_released = True
