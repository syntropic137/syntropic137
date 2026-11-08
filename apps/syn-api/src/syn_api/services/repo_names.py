"""The github context's ``RepoNamePort``, answered by the organization context.

A ``repo-…`` id is resolved through the organization context's Repo record;
``owner/name`` is GitHub's own form and passes through. Trigger registration
uses it to store the name GitHub knows, and the event poller to resolve
triggers stored before that (#1870).
"""

from __future__ import annotations

from syn_domain.contexts.github.ports import RepoNamePort


class OrganizationRepoNames(RepoNamePort):
    """Resolves syn137 repo ids to ``owner/name`` through the repo projection."""

    async def full_name(self, repository: str) -> str | None:
        if repository.startswith("repo-"):
            from syn_domain.contexts.organization import get_repo_projection

            repo = await get_repo_projection().get(repository)
            return repo.full_name if repo is not None else None
        if "/" in repository:
            return repository
        return None
