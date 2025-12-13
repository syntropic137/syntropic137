"""Installation suspended/unsuspended event.

Emitted when a GitHub App installation is suspended or unsuspended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class InstallationSuspendedEvent:
    """Event emitted when a GitHub App installation is suspended.

    Attributes:
        installation_id: The GitHub installation ID.
        suspended: True if suspended, False if unsuspended.
        event_id: Unique event identifier.
        occurred_at: When the event occurred.
    """

    installation_id: str
    suspended: bool
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

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
