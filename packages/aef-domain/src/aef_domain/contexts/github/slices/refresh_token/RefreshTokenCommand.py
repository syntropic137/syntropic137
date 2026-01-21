"""Refresh Token command.

Command to refresh an installation access token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RefreshTokenCommand:
    """Command to refresh an installation access token.

    This command can be issued:
    - When a cached token is about to expire
    - When an API call fails with an authentication error
    - Proactively before starting a long-running operation

    Attributes:
        command_id: Unique identifier for this command.
        installation_id: GitHub installation ID to refresh token for.
        force: Force refresh even if current token is valid.
    """

    installation_id: str
    force: bool = False
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.installation_id:
            raise ValueError("installation_id is required")
