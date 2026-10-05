"""GitHub adapter for ``PullRequestCommenter`` (#1547).

Posts with the platform's App installation, host-side: agents never hold
pull_requests:write. Idempotent on the forge as well as in the to-do list: a
known ``comment_id`` is edited, and without one the PR's comments are searched
for the notice's marker before anything new is posted, so a post whose id was
lost before it was stored is edited rather than doubled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, TypeAdapter

from syn_domain.contexts.orchestration import PullRequestCommenter

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient


class _Comment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    body: str | None = None


_PAGE_SIZE = 100

_COMMENTS: TypeAdapter[list[_Comment]] = TypeAdapter(list[_Comment])


class GitHubPullRequestCommenter(PullRequestCommenter):
    """Creates or edits one marked comment on a GitHub PR."""

    def __init__(self, client_factory: Callable[[], GitHubAppClient]) -> None:
        self._client_factory = client_factory

    async def upsert_comment(
        self,
        repository: str,
        pull_request: int,
        *,
        marker: str,
        body: str,
        comment_id: int | None,
    ) -> int:
        client = self._client_factory()
        installation_id = await client.get_installation_for_repo(repository)
        existing = comment_id
        if existing is None:
            existing = await self._find_marked(
                client, repository, pull_request, marker, installation_id
            )
        if existing is not None:
            await client.api_patch(
                f"/repos/{repository}/issues/comments/{existing}", {"body": body}, installation_id
            )
            return existing
        created = await client.api_post(
            f"/repos/{repository}/issues/{pull_request}/comments", {"body": body}, installation_id
        )
        return _Comment.model_validate(created).id

    @staticmethod
    async def _find_marked(
        client: GitHubAppClient,
        repository: str,
        pull_request: int,
        marker: str,
        installation_id: str,
    ) -> int | None:
        """The comment carrying ``marker``, searched across EVERY page.

        Stopping at the first page would post a duplicate on any PR busy
        enough that the notice has scrolled past its first hundred comments.
        """
        page = 1
        while True:
            listed: object = await client.api_get(
                f"/repos/{repository}/issues/{pull_request}/comments"
                f"?per_page={_PAGE_SIZE}&page={page}",
                installation_id,
            )
            comments = _COMMENTS.validate_python(listed)
            found = next((c.id for c in comments if marker in (c.body or "")), None)
            if found is not None or len(comments) < _PAGE_SIZE:
                return found
            page += 1
