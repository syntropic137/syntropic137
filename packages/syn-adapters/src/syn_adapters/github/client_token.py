"""GitHub App installation token management.

Extracted from client.py to reduce module complexity.
Handles token response validation, parsing, caching, and retrieval.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient, InstallationToken

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
    cache_key: str | None = None,
) -> InstallationToken:
    """Parse and cache an installation token from API response data.

    Args:
        data: JSON response from GitHub token endpoint
        iid: Installation ID, for the log line
        cached_tokens: Token cache dict to update
        cache_key: Cache entry to write. Defaults to ``iid``; a token minted
            with a reduced permission set stores itself elsewhere so it is
            never served to a caller that asked for the full one, or vice
            versa (#1197).

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
    cached_tokens[cache_key if cache_key is not None else iid] = token

    logger.info(
        "Installation token generated (installation_id=%s, expires_at=%s, permissions=%s)",
        iid,
        expires_at.isoformat(),
        list(token.permissions.keys()),
    )

    return token


def _cache_key(iid: str, permissions: Mapping[str, str] | None) -> str:
    """Cache slot for a token, distinguishing the permission set it carries.

    Keying on the installation id alone was correct while every token was the
    installation's full grant. It stops being correct the moment two callers
    want different grants from one installation, which is what a
    non-publishing phase asks for (#1197): the cache would hand it whichever
    token happened to be minted first.
    """
    if permissions is None:
        return iid
    scope = ",".join(f"{name}={level}" for name, level in sorted(permissions.items()))
    return f"{iid}#{scope}"


async def get_installation_token(
    client: GitHubAppClient,
    installation_id: str | None = None,
    force_refresh: bool = False,
    permissions: Mapping[str, str] | None = None,
) -> str:
    """Get a valid installation access token.

    Tokens are cached per installation_id and permission set, and reused
    until expired.

    Args:
        client: GitHubAppClient instance.
        installation_id: The installation to get a token for. Use
            get_installation_for_repo() to resolve this from a repo name. Raises if not set.
        force_refresh: If True, always fetch a new token.
        permissions: Restrict the token to this subset of the installation's
            own permissions (ADR-024 specified this parameter; it was never
            wired up until #1197). None requests the installation's full
            grant. GitHub rejects a set that exceeds what the installation
            holds, so callers derive theirs from it rather than enumerating -
            see ``agent_token.mint_agent_token``.

    Returns:
        Installation access token string.

    Raises:
        GitHubAuthError: If token generation fails or no installation_id available.
        GitHubRateLimitError: If rate limited.
    """
    from syn_adapters.github.client import GitHubAuthError

    if not installation_id:
        msg = (
            "No installation_id provided. Use get_installation_for_repo() to resolve it "
            "from a repository name, or pass it explicitly (e.g. from a webhook payload)."
        )
        raise GitHubAuthError(msg)
    iid = installation_id
    key = _cache_key(iid, permissions)

    # Return cached token if valid
    cached = client._cached_tokens.get(key)
    if not force_refresh and cached and not cached.is_expired:
        logger.debug(
            "Using cached installation token (installation_id=%s, expires_in=%ss)",
            iid,
            f"{cached.seconds_until_expiry:.0f}",
        )
        return cached.token

    logger.info("Generating new installation token for installation_id=%s", iid)

    jwt_token = client._generate_jwt()

    try:
        response = await client._http.post(
            f"/app/installations/{iid}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json=None if permissions is None else {"permissions": dict(permissions)},
        )

        check_token_response(response, iid)

        token = parse_installation_token(response.json(), iid, client._cached_tokens, key)
        return token.token

    except httpx.HTTPError as e:
        msg = f"HTTP error generating token: {e}"
        raise GitHubAuthError(msg) from e
