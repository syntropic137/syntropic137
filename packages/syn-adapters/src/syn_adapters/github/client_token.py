"""GitHub App installation token management.

Extracted from client.py to reduce module complexity.
Handles token response validation, parsing, caching, and retrieval.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict

from syn_adapters.github.client_retry import RETRY_SAFE

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

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
    full permission set.

    Open-ended by necessity rather than by neglect: which permissions an
    installation holds is operator-configured, and GitHub rejects a request
    exceeding that set, so callers derive this from the installation instead
    of enumerating it - see ``agent_token.mint_agent_token``.
    """

    repositories: list[str] | None = None
    """Repository NAMES (no owner) the token may reach, or None for every
    repository the installation covers (#725).

    Without it a token minted for one repository reaches all of them: an
    installation on an org is typically installed on every repo in it, so a
    phase working on `org/a` held a credential that could push to `org/b`.
    Names only, because an installation belongs to one account and GitHub
    resolves the owner from it; a name the installation does not cover is a
    422, which is the refusal we want rather than a token that quietly omits it.
    """

    def to_json(self) -> dict[str, object] | None:
        """The body as it goes on the wire, or None when it would say nothing.

        None is not an empty object: no body at all is the request GitHub reads
        as "the installation's full grant, every repository", and it is what a
        caller that restricts nothing has always sent.
        """
        body = self.model_dump(exclude_none=True)
        return body or None


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

    # Levels, not just keys. A `pull_requests: read` token and a
    # `pull_requests: write` token carry the SAME keys, so logging
    # `list(permissions.keys())` renders them identically - and reads as
    # positive confirmation that publishing is permitted when it is the
    # opposite. That line was quoted as proof a token could open a PR during
    # #1429, sending the investigation to the GitHub App's permissions,
    # installation repo selection and app identity, all of which were correct.
    # The cause then was a phase that had not declared `can_open_pr`; since
    # #1477 phase tokens are no longer downgraded, but a caller passing a
    # permission subset still needs the levels logged, not just the keys.
    #
    # Sorted so two log lines can be compared by eye without dict ordering
    # getting in the way.
    logger.info(
        "Installation token generated (installation_id=%s, expires_at=%s, permissions=%s)",
        iid,
        expires_at.isoformat(),
        _loggable_permissions(token.permissions),
    )

    return token


#: The levels GitHub documents for an installation permission. Anything else is
#: not a level, and this module will not print it.
_PERMISSION_LEVELS = frozenset({"read", "write", "admin"})

#: A permission NAME is a lowercase identifier. GitHub spells them
#: `pull_requests`, `contents`, `metadata`. Anything else did not come from the
#: permissions map as this code understands it.
_PERMISSION_NAME = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")


def _loggable_permissions(permissions: Mapping[str, str]) -> dict[str, str]:
    """The permission map, reduced to pairs that are safe to print.

    Logging LEVELS rather than keys is what makes this line useful: a
    `pull_requests: read` token and a `pull_requests: write` one are otherwise
    indistinguishable in the log, and that ambiguity cost a multi-hour
    investigation (#1429).

    Printing the values means the log now renders whatever the API returned.
    `parse_installation_token` copies `data["permissions"]` verbatim into the
    dataclass without enforcing a shape, so an unexpected payload could carry a
    credential in either position. A log line is exactly where that must not
    surface, so both halves are validated against what a permission actually
    looks like, and anything else is counted rather than shown.

    Sorted, so two lines can be compared by eye without dict ordering getting
    in the way.
    """
    safe: dict[str, str] = {}
    rejected = 0
    for name in sorted(permissions):
        level = permissions[name]
        if _PERMISSION_NAME.fullmatch(name) and level in _PERMISSION_LEVELS:
            safe[name] = level
        else:
            rejected += 1
    if rejected:
        # Named, not silently dropped: a permissions map that does not look
        # like one is worth knowing about, and the COUNT carries that without
        # printing the thing that failed the check.
        safe["<unprintable>"] = str(rejected)
    return safe


def _cache_key(
    iid: str,
    permissions: Mapping[str, str] | None,
    repositories: Collection[str] | None = None,
) -> str:
    """Cache slot for a token, distinguishing everything that scopes it.

    Keying on the installation id alone was correct while every token was the
    installation's full grant. It stops being correct the moment two callers
    want different grants from one installation, which is what a
    non-publishing phase asks for (#1197): the cache would hand it whichever
    token happened to be minted first. The repository set is the same
    argument one axis over (#725): a token scoped to `a` served to a caller
    that asked for `b` is a 403, and the reverse is a token reaching a repo
    its holder was never meant to touch.
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
) -> str:
    """Get a valid installation access token string.

    See `installation_token`, which this unwraps.
    """
    token = await installation_token(
        client, installation_id, force_refresh=force_refresh, permissions=permissions
    )
    return token.token


async def installation_token(
    client: GitHubAppClient,
    installation_id: str | None = None,
    *,
    force_refresh: bool = False,
    permissions: Mapping[str, str] | None = None,
    repositories: Collection[str] | None = None,
) -> InstallationToken:
    """Get a valid installation access token, with when it expires.

    Tokens are cached per installation_id, permission set and repository set,
    and reused until expired.

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
        repositories: Restrict the token to these repository names (#725).
            None reaches every repository the installation covers.

    Returns:
        The installation token, including its expiry.

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
        return cached

    logger.info("Generating new installation token for installation_id=%s", iid)

    jwt_token = client._generate_jwt()
    body = TokenRequest(
        permissions=None if permissions is None else dict(permissions),
        repositories=None if repositories is None else sorted(set(repositories)),
    )

    try:
        response = await client._http.post(
            f"/app/installations/{iid}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json=body.to_json(),
            # A POST, but sending it twice costs one extra token that expires
            # within the hour. Failing provisioning on a dropped connection
            # costs the execution (#1593).
            extensions=RETRY_SAFE,
        )

        check_token_response(response, iid)

        return parse_installation_token(response.json(), iid, client._cached_tokens, key)

    except httpx.HTTPError as e:
        msg = f"HTTP error generating token: {e}"
        raise GitHubAuthError(msg) from e


async def revoke_installation_token(client: GitHubAppClient, token: str) -> None:
    """Revoke an installation token before GitHub would expire it (#725).

    Minting a new token does NOT revoke older ones: every token lives its full
    hour unless its holder ends it, and the only credential that can end it is
    the token itself - ``DELETE /installation/token`` authenticates with the
    token being revoked, not with the App's JWT. So whoever minted a token and
    wants it gone early has to have kept it, which is why workspaces keep an
    issuance ledger.

    Raises:
        GitHubAuthError: GitHub did not confirm the revocation. A 401 is
            included deliberately: it usually means the token had already
            expired or been revoked, but "usually" is not something to report
            as a revocation that happened.
    """
    from syn_adapters.github.client import GitHubAuthError

    try:
        response = await client._http.delete(
            "/installation/token",
            headers={"Authorization": f"token {token}"},
        )
    except httpx.HTTPError as e:
        msg = f"HTTP error revoking installation token: {e}"
        raise GitHubAuthError(msg) from e
    if response.status_code != 204:
        msg = f"Installation token revocation answered {response.status_code}"
        raise GitHubAuthError(msg)
