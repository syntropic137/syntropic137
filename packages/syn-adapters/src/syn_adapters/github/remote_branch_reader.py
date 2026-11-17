"""GitHub adapter for ``RemoteBranchPort`` (#1513).

Reads ``GET /repos/{slug}/branches/{branch}`` for where the branch is now and
``GET /repos/{slug}/pulls?head={owner}:{branch}&state=all`` for the PRs from
it, through the App installation that covers the repository. Total, as the
port requires: a 404 on the branch is the one answer read as "gone"; every
other failure is logged and becomes ``readable=False``, never "gone".

A name git cannot give a ref, such as the ``(detached HEAD)`` stand-in the
orchestration context persists where a branch goes, is answered "not on
origin" without a request: none can exist, and asking 404'd forever (#1870).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from syn_domain.contexts.orchestration.ports import RemoteBranchPort, RemoteBranchReading

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)

_NOT_FOUND = "GitHub API error 404"

#: Characters `git check-ref-format` refuses anywhere in a ref name.
_NOT_IN_A_REF = frozenset(" ~^:?*[\\\x7f")


class _Commit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


class _Branch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    commit: _Commit


class _Pull(BaseModel):
    model_config = ConfigDict(extra="ignore")
    number: int
    state: str


_PULLS: TypeAdapter[list[_Pull]] = TypeAdapter(list[_Pull])


class GitHubRemoteBranchReader(RemoteBranchPort):
    """Reads a branch's head and the PRs from it from GitHub.

    Takes a client FACTORY, like ``GitHubSourceCommitResolver``: an install
    without a configured App must still resume, starting fresh.
    """

    def __init__(self, client_factory: Callable[[], GitHubAppClient]) -> None:
        self._client_factory = client_factory

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        """Where ``branch`` is on origin and which PR is open from it."""
        from syn_adapters.github.client import GitHubAppError

        if not _is_ref_name(branch):
            return RemoteBranchReading(repository=repository, branch=branch, readable=True)
        unreadable = RemoteBranchReading(repository=repository, branch=branch, readable=False)
        try:
            client = self._client_factory()
            installation_id = await client.get_installation_for_repo(repository)
            head = await _head(client, repository, branch, installation_id)
            if head is None:
                return RemoteBranchReading(repository=repository, branch=branch, readable=True)
            pulls = await _pulls(client, repository, branch, installation_id)
        except (GitHubAppError, httpx.HTTPError, ValueError, ValidationError) as exc:
            logger.warning("Could not read branch %s of %s: %s", branch, repository, exc)
            return unreadable
        open_prs = [p.number for p in pulls if p.state == "open"]
        closed_prs = [p.number for p in pulls if p.state != "open"]
        return RemoteBranchReading(
            repository=repository,
            branch=branch,
            readable=True,
            head_sha=head,
            open_pull_request=max(open_prs, default=None),
            closed_pull_request=max(closed_prs, default=None),
        )


def _is_ref_name(branch: str) -> bool:
    """Whether git could have a branch by this name (the cheap half of its rules)."""
    return (
        bool(branch)
        and ".." not in branch
        and not any(c in _NOT_IN_A_REF or c < " " for c in branch)
    )


async def _head(
    client: GitHubAppClient, repository: str, branch: str, installation_id: str
) -> str | None:
    """The branch's head sha, or None when GitHub answers 404."""
    from syn_adapters.github.client import GitHubAppError

    try:
        body = await client.api_get(
            f"/repos/{repository}/branches/{quote(branch, safe='')}", installation_id
        )
    except GitHubAppError as exc:
        if str(exc).startswith(_NOT_FOUND):
            return None
        raise
    return _Branch.model_validate(body).commit.sha


async def _pulls(
    client: GitHubAppClient, repository: str, branch: str, installation_id: str
) -> list[_Pull]:
    """Every PR, open or closed, whose head is ``branch`` in ``repository``."""
    owner = repository.split("/", 1)[0]
    head = quote(f"{owner}:{branch}", safe=":")
    body: object = await client.api_get(
        f"/repos/{repository}/pulls?head={head}&state=all&per_page=100", installation_id
    )
    return _PULLS.validate_python(body)
