"""GitHub App adapter for the PullRequestConversation port (#1097).

Satisfies ``syn_domain...publish_review_verdict.PullRequestConversation``.
GitHub models pull request comments as ISSUE comments, so reads and writes go
to ``/repos/{owner}/{repo}/issues/{number}/comments`` rather than any
pulls endpoint -- a detail the domain deliberately does not carry.
"""

from __future__ import annotations

import logging

from syn_adapters.github.client import GitHubAppClient, get_github_client
from syn_adapters.github.client_api import check_response
from syn_adapters.github.client_endpoints import get_installation_for_repo

logger = logging.getLogger(__name__)

#: GitHub's maximum page size for comment listing.
_PER_PAGE = 100

#: Safety cap. 20 pages of 100 is far past any pull request a review would
#: reasonably run against, and bounds the work if Link headers ever mislead.
_MAX_PAGES = 20


class GitHubPullRequestConversation:
    """Reads and writes one pull request's comment thread via the GitHub App."""

    def __init__(self, client: GitHubAppClient | None = None) -> None:
        """Args:
        client: GitHub App client. Defaults to the process singleton.
        """
        self._client = client or get_github_client()
        self._installations: dict[str, str] = {}

    async def head_sha(self, repository: str, pr_number: int) -> str:
        """Return the pull request's current head commit SHA."""
        pull = await self._client.api_get(
            f"/repos/{repository}/pulls/{pr_number}",
            installation_id=await self._installation(repository),
        )
        head = pull.get("head")
        return str(head.get("sha", "")) if isinstance(head, dict) else ""

    async def comment_bodies(self, repository: str, pr_number: int) -> list[str]:
        """Return every comment body on the pull request, oldest first."""
        token = await self._client.get_installation_token(await self._installation(repository))
        headers = {"Authorization": f"Bearer {token}"}
        path = f"/repos/{repository}/issues/{pr_number}/comments"

        bodies: list[str] = []
        for page in range(1, _MAX_PAGES + 1):
            response = await self._client._http.get(
                path,
                headers=headers,
                params={"per_page": _PER_PAGE, "page": page},
            )
            check_response(response)
            batch = response.json()
            if not isinstance(batch, list):
                break
            bodies.extend(str(comment.get("body", "")) for comment in batch)
            if len(batch) < _PER_PAGE:
                break
        return bodies

    async def post_comment(self, repository: str, pr_number: int, body: str) -> None:
        """Append a comment to the pull request."""
        await self._client.api_post(
            f"/repos/{repository}/issues/{pr_number}/comments",
            json={"body": body},
            installation_id=await self._installation(repository),
        )
        logger.info("Posted comment on %s#%s", repository, pr_number)

    async def _installation(self, repository: str) -> str:
        """Installation id for a repository, resolved once per process."""
        cached = self._installations.get(repository)
        if cached is None:
            cached = await get_installation_for_repo(self._client, repository)
            self._installations[repository] = cached
        return cached
