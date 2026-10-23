"""GitHub App HTTP API helpers.

Extracted from client.py to reduce module complexity.
Handles low-level authenticated GET/POST/PUT requests and response checking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syn_adapters.github.client_retry import retry_after_seconds

if TYPE_CHECKING:
    import httpx

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)

_HTTP_TOO_MANY_REQUESTS = 429


def check_response(response: httpx.Response) -> None:
    """Check response for errors.

    Raises:
        GitHubRateLimitError: If rate limited - a 429, or a 403 that says so.
            ``reset_at`` is when GitHub said to try again: ``Retry-After``
            first, which is what a 429 and a secondary limit carry, then
            ``X-RateLimit-Reset``; None when GitHub said neither.
        GitHubAppError: On other errors.
    """
    from syn_adapters.github.client import GitHubAppError, GitHubRateLimitError

    if response.status_code == _HTTP_TOO_MANY_REQUESTS or (
        response.status_code == 403 and "rate limit" in response.text.lower()
    ):
        raise GitHubRateLimitError("Rate limit exceeded", reset_at=_rate_limit_reset(response))

    if response.status_code >= 400:
        msg = f"GitHub API error {response.status_code}: {response.text}"
        raise GitHubAppError(msg, status_code=response.status_code)


def _rate_limit_reset(response: httpx.Response) -> datetime | None:
    """When a rate-limited request may be sent again, or None when GitHub did not say."""
    wait = retry_after_seconds(response)
    if wait is not None:
        return datetime.now(UTC) + timedelta(seconds=wait)
    reset_header = response.headers.get("X-RateLimit-Reset")
    if reset_header:
        return datetime.fromtimestamp(int(reset_header), tz=UTC)
    return None


async def api_get(client: GitHubAppClient, path: str, installation_id: str | None = None) -> dict:
    """Make an authenticated GET request to the GitHub API.

    Args:
        client: GitHubAppClient instance.
        path: API path (e.g., "/repos/owner/repo").
        installation_id: Installation to authenticate as. Must be provided explicitly.

    Returns:
        Response JSON as dictionary.

    Raises:
        GitHubAppError: On API errors.
    """
    token = await client.get_installation_token(installation_id)

    response = await client._http.get(
        path,
        headers={"Authorization": f"Bearer {token}"},
    )

    check_response(response)
    return response.json()


async def api_post(
    client: GitHubAppClient,
    path: str,
    json: dict | None = None,
    installation_id: str | None = None,
) -> dict:
    """Make an authenticated POST request to the GitHub API.

    Args:
        client: GitHubAppClient instance.
        path: API path.
        json: Request body.
        installation_id: Installation to authenticate as. Must be provided explicitly.

    Returns:
        Response JSON as dictionary.

    Raises:
        GitHubAppError: On API errors.
    """
    token = await client.get_installation_token(installation_id)

    response = await client._http.post(
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=json,
    )

    check_response(response)
    return response.json()


async def api_put(
    client: GitHubAppClient,
    path: str,
    json: dict | None = None,
    installation_id: str | None = None,
) -> dict:
    """Make an authenticated PUT request to the GitHub API.

    Args:
        client: GitHubAppClient instance.
        path: API path.
        json: Request body.
        installation_id: Installation to authenticate as. Must be provided explicitly.

    Returns:
        Response JSON as dictionary.

    Raises:
        GitHubAppError: On API errors.
    """
    token = await client.get_installation_token(installation_id)

    response = await client._http.put(
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=json,
    )

    check_response(response)
    return response.json()


async def api_patch(
    client: GitHubAppClient,
    path: str,
    json: dict[str, str],
    installation_id: str | None = None,
) -> object:
    """Make an authenticated PATCH request to the GitHub API (#1547: edit a comment).

    Raises:
        GitHubAppError: On API errors.
    """
    token = await client.get_installation_token(installation_id)
    response = await client._http.patch(
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=json,
    )
    check_response(response)
    return response.json()
