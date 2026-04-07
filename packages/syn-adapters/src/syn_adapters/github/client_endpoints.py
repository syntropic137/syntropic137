"""GitHub App API endpoint helpers.

Extracted from client.py to reduce module complexity.
Handles app-level and installation-level GitHub API endpoint calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)


async def get_app_info(client: GitHubAppClient) -> dict:
    """Get information about the GitHub App.

    Returns:
        App metadata including name, ID, permissions.
    """
    from syn_adapters.github.client_api import check_response

    jwt_token = client._generate_jwt()

    response = await client._http.get(
        "/app",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )

    check_response(response)
    return response.json()


async def get_webhook_config(client: GitHubAppClient) -> dict:
    """Get the GitHub App's webhook configuration.

    Uses App-level JWT auth (not installation tokens).

    Returns:
        Webhook config including url, content_type, insecure_ssl, secret.
    """
    from syn_adapters.github.client_api import check_response

    jwt_token = client._generate_jwt()

    response = await client._http.get(
        "/app/hook/config",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )

    check_response(response)
    return response.json()


async def update_webhook_config(
    client: GitHubAppClient,
    url: str,
    content_type: str = "json",
    insecure_ssl: str = "0",
    secret: str | None = None,
) -> dict:
    """Update the GitHub App's webhook configuration.

    Uses App-level JWT auth (not installation tokens).

    Args:
        client: GitHubAppClient instance.
        url: The webhook URL to receive events.
        content_type: Payload content type ('json' or 'form').
        insecure_ssl: '0' to verify SSL, '1' to skip verification.
        secret: Webhook secret for payload signing. If None, keeps existing.

    Returns:
        Updated webhook config.
    """
    from syn_adapters.github.client_api import check_response

    jwt_token = client._generate_jwt()

    payload: dict[str, str] = {
        "url": url,
        "content_type": content_type,
        "insecure_ssl": insecure_ssl,
    }
    if secret is not None:
        payload["secret"] = secret

    response = await client._http.patch(
        "/app/hook/config",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json=payload,
    )

    check_response(response)
    return response.json()


async def list_installations(client: GitHubAppClient) -> list[dict]:
    """List all installations of this GitHub App.

    Returns:
        List of installation metadata.
    """
    from syn_adapters.github.client_api import check_response

    jwt_token = client._generate_jwt()

    response = await client._http.get(
        "/app/installations",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )

    check_response(response)
    return response.json()


async def list_accessible_repos(
    client: GitHubAppClient, installation_id: str | None = None
) -> list[dict]:
    """List repositories accessible to an installation.

    Paginates through all pages of the GitHub API response.
    GitHub returns max 100 items per page with ``per_page=100``.

    Args:
        client: GitHubAppClient instance.
        installation_id: The installation to list repos for. Must be provided explicitly.

    Returns:
        List of repository metadata dicts.
    """
    from syn_adapters.github.client_api import check_response

    token = await client.get_installation_token(installation_id)
    headers = {"Authorization": f"Bearer {token}"}

    all_repos: list[dict] = []
    page = 1
    max_pages = 50  # Safety cap: 50 pages * 100 = 5,000 repos
    total_count = 0

    while page <= max_pages:
        response = await client._http.get(
            "/installation/repositories",
            headers=headers,
            params={"per_page": 100, "page": page},
        )
        check_response(response)

        data = response.json()
        repos: list[dict] = data.get("repositories", [])
        all_repos.extend(repos)

        total_count: int | None = data.get("total_count")
        if total_count is not None and len(all_repos) >= total_count:
            break
        if len(repos) < 100:
            break

        page += 1

    if page > max_pages and len(all_repos) < total_count:
        import logging

        logging.getLogger(__name__).warning(
            "Pagination safety cap reached (%d pages). Returned %d of %d repos.",
            max_pages,
            len(all_repos),
            total_count,
        )

    return all_repos


async def get_installation_for_repo(client: GitHubAppClient, repo_full_name: str) -> str:
    """Look up the installation ID for a repository.

    Calls GET /repos/{owner}/{repo}/installation with App JWT auth.
    Requires the GitHub App to be installed on the repo's owner account.

    Args:
        client: GitHubAppClient instance.
        repo_full_name: Repository in "{owner}/{repo}" format.

    Returns:
        Installation ID string.

    Raises:
        GitHubAuthError: If lookup fails or app not installed on repo.
    """
    from syn_adapters.github.client import GitHubAuthError
    from syn_adapters.github.client_api import check_response

    jwt_token = client._generate_jwt()
    response = await client._http.get(
        f"/repos/{repo_full_name}/installation",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    if response.status_code == 404:
        msg = f"GitHub App not installed on repository: {repo_full_name}"
        raise GitHubAuthError(msg)
    check_response(response)
    installation_id = str(response.json()["id"])
    logger.debug("Resolved installation_id=%s for repo %s", installation_id, repo_full_name)
    return installation_id
