"""GitHub App installation token management.

Extracted from client.py to reduce module complexity.
Handles token response validation, parsing, and caching.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from syn_adapters.github.client import InstallationToken

logger = logging.getLogger(__name__)


def check_token_response(response: httpx.Response, iid: str) -> None:
    """Check installation token response for errors.

    Args:
        response: HTTP response from token endpoint
        iid: Installation ID (for error messages)

    Raises:
        GitHubAuthError: On 401, 403 (non-rate-limit), or 404.
        GitHubRateLimitError: On 403 with rate limit.
    """
    from syn_adapters.github.client import GitHubAuthError, GitHubRateLimitError

    if response.status_code == 401:
        msg = "JWT authentication failed - check App ID and private key"
        raise GitHubAuthError(msg)

    if response.status_code == 403:
        if "rate limit" in response.text.lower():
            reset_header = response.headers.get("X-RateLimit-Reset")
            reset_at = None
            if reset_header:
                reset_at = datetime.fromtimestamp(int(reset_header), tz=UTC)
            raise GitHubRateLimitError("Rate limit exceeded", reset_at=reset_at)
        msg = f"Permission denied: {response.text}"
        raise GitHubAuthError(msg)

    if response.status_code == 404:
        msg = f"Installation {iid} not found"
        raise GitHubAuthError(msg)

    response.raise_for_status()


def parse_installation_token(
    data: dict,
    iid: str,
    cached_tokens: dict[str, InstallationToken],
) -> InstallationToken:
    """Parse and cache an installation token from API response data.

    Args:
        data: JSON response from GitHub token endpoint
        iid: Installation ID for cache key
        cached_tokens: Token cache dict to update

    Returns:
        Parsed InstallationToken.
    """
    from syn_adapters.github.client import InstallationToken

    expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

    token = InstallationToken(
        token=data["token"],
        expires_at=expires_at,
        permissions=data.get("permissions", {}),
        repository_selection=data.get("repository_selection", "all"),
    )
    cached_tokens[iid] = token

    logger.info(
        "Installation token generated (installation_id=%s, expires_at=%s, permissions=%s)",
        iid,
        expires_at.isoformat(),
        list(token.permissions.keys()),
    )

    return token
