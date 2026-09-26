"""GitHub App installation token management.

Extracted from client.py to reduce module complexity.
Handles token response validation, parsing, caching, and retrieval.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_adapters.github.client import GitHubAppClient, InstallationToken

logger = logging.getLogger(__name__)


class TokenRequest(BaseModel):
    """The body of ``POST /app/installations/{id}/access_tokens``.

    This endpoint's scoping contract, in one place: send this body and the
    token carries exactly ``permissions``; send no body at all and it carries
    the installation's full grant. The second case is what let a phase that
    had been told not to publish publish anyway (#1197), so which of the two
    went on the wire is the thing worth asserting on - and asserting on it
    should not mean re-deriving the JSON shape at every call site.

    Being a model rather than a dict literal is what makes the field name a
    single edit: rename it here and pyright finds every reader, instead of the
    scope silently going missing at runtime. ``extra="forbid"`` closes the
    other direction, where a body grows a key the endpoint ignores.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    permissions: dict[str, str] | None = None
    """Permission name to level, spelled as GitHub spells them
    (``pull_requests``, ``contents``, ...). None asks for the installation's
    full grant.

    Open-ended by necessity rather than by neglect: which permissions an
    installation holds is operator-configured, and GitHub rejects a request
    exceeding that set, so callers derive this from the installation instead
    of enumerating it - see ``agent_token.mint_agent_token``.
    """

    repositories: list[str] | None = None
    """Repository NAMES, without the owner, the token may reach (#725).

    None reaches every repository the installation covers. An agent's token
    names the repos its workflow works on, so a credential that outlives its
    phase - or leaks from one - opens those and nothing else. GitHub takes
    at most 500 and rejects a name the installation does not cover.
    """

    def body(self) -> dict[str, dict[str, str] | list[str]] | None:
        """The JSON actually posted: absent fields are omitted, not sent as null.

        No body at all when nothing is restricted, which is the documented
        spelling of "the installation's full grant".
        """
        dumped = self.model_dump(exclude_none=True)
        return dumped or None


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


def parse_installation_token(data: dict, iid: str) -> InstallationToken:
    """Parse an installation token from API response data.

    Caching is the caller's decision (see ``get_installation_token``): a
    token minted for an agent workspace must never be cached (#725).

    Args:
        data: JSON response from GitHub token endpoint
        iid: Installation ID, for the log line

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

    logger.info(
        "Installation token generated (installation_id=%s, expires_at=%s, permissions=%s)",
        iid,
        expires_at.isoformat(),
        list(token.permissions.keys()),
    )

    return token


def _cache_key(
    iid: str,
    permissions: Mapping[str, str] | None,
    repositories: Sequence[str] | None = None,
) -> str:
    """Cache slot for a token: (installation, repo set, permission set).

    Keying on the installation id alone was correct while every token was the
    installation's full grant. It stops being correct the moment two callers
    want different grants from one installation, which is what a
    non-publishing phase asks for (#1197): the cache would hand it whichever
    token happened to be minted first. A repo-scoped token (#725) is the same
    problem on the other axis: a token for repo A served to a caller asking
    for repo B would 404 on B.
    """
    key = iid
    if permissions is not None:
        key += "#" + ",".join(f"{name}={level}" for name, level in sorted(permissions.items()))
    if repositories is not None:
        key += "@" + ",".join(sorted(set(repositories)))
    return key


async def get_installation_token(
    client: GitHubAppClient,
    installation_id: str | None = None,
    force_refresh: bool = False,
    permissions: Mapping[str, str] | None = None,
    repositories: Sequence[str] | None = None,
) -> str:
    """Get a valid installation access token.

    Tokens are cached per installation_id, repo set and permission set, and
    reused until expired.

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
        repositories: Restrict the token to these repository names (without
            the owner). None reaches every repo the installation covers.

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
    key = _cache_key(iid, permissions, repositories)

    # Return cached token if valid
    cached = client._cached_tokens.get(key)
    if not force_refresh and cached and not cached.is_expired:
        logger.debug(
            "Using cached installation token (installation_id=%s, expires_in=%ss)",
            iid,
            f"{cached.seconds_until_expiry:.0f}",
        )
        return cached.token

    token = await request_installation_token(
        client, iid, permissions=permissions, repositories=repositories
    )
    client._cached_tokens[key] = token
    return token.token


async def request_installation_token(
    client: GitHubAppClient,
    installation_id: str,
    *,
    permissions: Mapping[str, str] | None = None,
    repositories: Sequence[str] | None = None,
) -> InstallationToken:
    """Mint a NEW installation token, bypassing and never writing the cache.

    For a token whose life is owned by someone else - an agent workspace that
    renews it and revokes it at teardown (#725). Caching those would be
    wrong both ways: a renewal would be handed the token it is trying to
    replace, and a revocation would kill a token another workspace had been
    served from the cache.

    Raises:
        GitHubAuthError: If token generation fails.
        GitHubRateLimitError: If rate limited.
    """
    from syn_adapters.github.client import GitHubAuthError

    logger.info("Generating new installation token for installation_id=%s", installation_id)

    jwt_token = client._generate_jwt()
    request = TokenRequest(
        permissions=None if permissions is None else dict(permissions),
        repositories=None if repositories is None else list(repositories),
    )

    try:
        response = await client._http.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json=request.body(),
        )

        check_token_response(response, installation_id)

        return parse_installation_token(response.json(), installation_id)

    except httpx.HTTPError as e:
        msg = f"HTTP error generating token: {e}"
        raise GitHubAuthError(msg) from e


async def revoke_installation_token(client: GitHubAppClient, token: str) -> None:
    """Revoke an installation token: ``DELETE /installation/token`` (#725).

    Authenticated WITH the token being revoked - the endpoint takes no id,
    the credential is the argument. Minting never revokes earlier tokens, so
    without this every token a workspace was issued stays live for its full
    hour after the workspace is gone.

    Raises:
        httpx.HTTPError: On transport failure or a non-2xx answer. An
            already-expired or already-revoked token answers 401.
    """
    response = await client._http.delete(
        "/installation/token",
        headers={"Authorization": f"token {token}"},
    )
    response.raise_for_status()
