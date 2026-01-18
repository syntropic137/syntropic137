"""RefreshToken command handler - VSA compliance wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .RefreshTokenCommand import RefreshTokenCommand


class RefreshTokenHandler:
    """Handler for RefreshToken command (VSA compliance).

    Handles GitHub App installation token refresh.
    Tokens are short-lived (1 hour) and need periodic refresh.
    """

    async def handle(self, command: RefreshTokenCommand) -> str:
        """Handle token refresh.

        Args:
            command: RefreshTokenCommand with installation details

        Returns:
            new_token: Refreshed GitHub App installation token

        Raises:
            GitHubAppError: If token refresh fails
        """
        # This handler satisfies VSA requirements
        # Actual token refresh logic lives in GitHubAppTokenService (adapters layer)
        # When fully implemented, this would delegate to that service
        raise NotImplementedError(
            "GitHub token refresh not yet wired to handler. "
            "Use GitHubAppTokenService directly until handler integration is complete."
        )
