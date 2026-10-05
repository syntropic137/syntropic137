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

from syn_domain.contexts.orchestration.slices.notify_quarantine import PullRequestCommenter

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient


class _Comment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    body: str | None = None


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
            listed: object = await client.api_get(
                f"/repos/{repository}/issues/{pull_request}/comments?per_page=100",
                installation_id,
            )
            existing = next(
                (c.id for c in _COMMENTS.validate_python(listed) if marker in (c.body or "")),
                None,
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
