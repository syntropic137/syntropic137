"""Installation suspended/unsuspended event.

Emitted when a GitHub App installation is suspended or unsuspended.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event


@event("github.InstallationSuspended", "v1")
class InstallationSuspendedEvent(DomainEvent):
    """Event emitted when a GitHub App installation is suspended.

    Inherits from DomainEvent which provides:
    - Immutability (frozen=True)
    - Strict validation (extra='forbid')
    - JSON serialization
    """

    installation_id: str
    suspended: bool

    @classmethod
    def from_webhook(cls, payload: dict[str, Any], action: str) -> InstallationSuspendedEvent:
        """Create event from a GitHub webhook payload.

        Args:
            payload: The webhook payload.
            action: The webhook action ('suspend' or 'unsuspend').

        Returns:
            InstallationSuspendedEvent instance.
        """
        installation = payload.get("installation", {})

        return cls(
            installation_id=str(installation.get("id", "")),
            suspended=action == "suspend",
        )
