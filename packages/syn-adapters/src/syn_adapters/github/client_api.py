"""GitHub App HTTP API helpers.

Extracted from client.py to reduce module complexity.
Handles low-level authenticated GET/POST/PUT requests and response checking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)


def check_response(response: httpx.Response) -> None:
    """Check response for errors.

    Raises:
        GitHubRateLimitError: If rate limited.
        GitHubAppError: On other errors.
    """
    from syn_adapters.github.client import GitHubAppError, GitHubRateLimitError

    if response.status_code == 403 and "rate limit" in response.text.lower():
        reset_header = response.headers.get("X-RateLimit-Reset")
        reset_at = None
        if reset_header:
            reset_at = datetime.fromtimestamp(int(reset_header), tz=UTC)
        raise GitHubRateLimitError("Rate limit exceeded", reset_at=reset_at)

    if response.status_code >= 400:
        msg = f"GitHub API error {response.status_code}: {response.text}"
        raise GitHubAppError(msg)


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
