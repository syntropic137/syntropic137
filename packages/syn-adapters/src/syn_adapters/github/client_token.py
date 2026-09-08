"""GitHub App installation token management.

Extracted from client.py to reduce module complexity.
Handles token response validation, parsing, caching, and retrieval.
"""

from __future__ import annotations

import logging
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


#: What a read-only installation token is allowed to do.
#:
#: Everything an agent that reviews other work needs, and nothing that lets it
#: publish: clone, fetch, read the PR and its checks. GitHub enforces this at
#: the API, so a `git push` with one of these fails 403 no matter what the
#: agent believes it is allowed to do (#1161).
#:
#: A subset request never widens a token: GitHub intersects it with what the
#: installation actually has, so an App missing `checks` yields a token
#: without it rather than an error.
READ_ONLY_TOKEN_PERMISSIONS: dict[str, str] = {
    "contents": "read",
    "pull_requests": "read",
    "issues": "read",
    "metadata": "read",
    "checks": "read",
}


def token_cache_key(installation_id: str, *, read_only: bool) -> str:
    """Cache key for an installation token at a given scope.

    Scope is part of the identity, not a detail of it. Keying on the
    installation alone would let a read-only phase's token be handed to a
    phase that needs to push - or, far worse, the reverse: one push-capable
    phase warming the cache would silently restore push access to every
    verify phase after it, and nothing downstream would look any different.
    """
    return f"{installation_id}:ro" if read_only else installation_id


def parse_installation_token(
    data: dict,
    iid: str,
    cached_tokens: dict[str, InstallationToken],
) -> InstallationToken:
    """Parse and cache an installation token from API response data.

    Args:
        data: JSON response from GitHub token endpoint
        iid: Cache key to store under - ``token_cache_key(...)``, not a bare
            installation id, because scope is part of a token's identity.
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


async def get_installation_token(
    client: GitHubAppClient,
    installation_id: str | None = None,
    force_refresh: bool = False,
    *,
    read_only: bool = False,
) -> str:
    """Get a valid installation access token.

    Tokens are cached per (installation_id, scope) and reused until expired.

    Args:
        client: GitHubAppClient instance.
        installation_id: The installation to get a token for. Use
            get_installation_for_repo() to resolve this from a repo name. Raises if not set.
        force_refresh: If True, always fetch a new token.
        read_only: If True, mint a token GitHub itself will refuse to write
            with (``READ_ONLY_TOKEN_PERMISSIONS``). The caller gets a
            credential that clones, fetches and reads pull requests but
            cannot push (#1161).

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
    cache_key = token_cache_key(iid, read_only=read_only)

    # Return cached token if valid
    cached = client._cached_tokens.get(cache_key)
    if not force_refresh and cached and not cached.is_expired:
        logger.debug(
            "Using cached installation token (installation_id=%s, expires_in=%ss)",
            iid,
            f"{cached.seconds_until_expiry:.0f}",
        )
        return cached.token

    logger.info(
        "Generating new installation token (installation_id=%s, read_only=%s)",
        iid,
        read_only,
    )

    jwt_token = client._generate_jwt()

    try:
        response = await client._http.post(
            f"/app/installations/{iid}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
            # Omitted entirely for the default scope. Posting `{}` is NOT the
            # same request as posting no body: an empty permissions object is
            # a request for no permissions at all.
            json=(
                {"permissions": READ_ONLY_TOKEN_PERMISSIONS.copy()} if read_only else None
            ),
        )

        check_token_response(response, iid)

        token = parse_installation_token(response.json(), cache_key, client._cached_tokens)
        return token.token

    except httpx.HTTPError as e:
        msg = f"HTTP error generating token: {e}"
        raise GitHubAuthError(msg) from e
