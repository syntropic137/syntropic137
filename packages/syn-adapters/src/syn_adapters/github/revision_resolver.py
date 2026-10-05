"""GitHub adapter for ``RevisionResolverPort`` (evals plan, #967).

Reads ``GET /repos/{slug}/commits/{ref}`` through the App installation that
covers the repository. That one endpoint resolves a branch, a tag or a sha
(abbreviated or full) to the commit it names, so the adapter never has to
guess which kind of ref it was given.

Total, as the port requires: every way GitHub cannot answer is an
``UnresolvedRevision`` naming why, never an exception.

- no installation covers the repository, the App is not configured, or
  GitHub refuses the read (401/403) -> ``NO_ACCESS``
- the repository answered and has no such ref (404, or 422 for a sha it
  does not hold) -> ``NOT_FOUND``
- a rate limit, a 5xx, a network error, or an answer that is not a full
  commit sha -> ``UNAVAILABLE``, which is retryable
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.orchestration._shared.repository_baseline import FULL_COMMIT_SHA
from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
    ResolvedRevision,
    RevisionResolution,
    RevisionResolverPort,
    UnresolvedReason,
    UnresolvedRevision,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient, GitHubAppError
    from syn_domain.contexts._shared.repository_ref import RepositoryRef

logger = logging.getLogger(__name__)

#: Statuses that mean the repository answered and the ref is not in it.
_NOT_FOUND_STATUSES = frozenset({404, 422})
#: Statuses that mean the credentials available cannot read the repository.
_NO_ACCESS_STATUSES = frozenset({401, 403})


class _Commit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


class GitHubRevisionResolver(RevisionResolverPort):
    """Pins a branch, tag or sha in a GitHub repository to a full commit sha.

    Takes a client FACTORY, like ``GitHubSourceCommitResolver``:
    ``get_github_client`` raises on an unconfigured App, and that is an
    answer (``NO_ACCESS``) the caller must be able to report.
    """

    def __init__(self, client_factory: Callable[[], GitHubAppClient]) -> None:
        self._client_factory = client_factory

    async def resolve(self, repository: RepositoryRef, requested_ref: str, /) -> RevisionResolution:
        """The full lowercase commit sha ``requested_ref`` names in ``repository``."""
        from syn_adapters.github.client import GitHubAppError, GitHubAuthError

        try:
            client = self._client_factory()
        except (GitHubAppError, ValueError) as exc:
            return _unresolved(UnresolvedReason.NO_ACCESS, repository, requested_ref, exc)
        try:
            installation_id = await client.get_installation_for_repo(repository.slug)
            body = await client.api_get(
                f"/repos/{repository.slug}/commits/{quote(requested_ref, safe='')}",
                installation_id,
            )
            sha = _Commit.model_validate(body).sha.lower()
        except GitHubAuthError as exc:
            return _unresolved(UnresolvedReason.NO_ACCESS, repository, requested_ref, exc)
        except GitHubAppError as exc:
            return _unresolved(_reason_for(exc), repository, requested_ref, exc)
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            return _unresolved(UnresolvedReason.UNAVAILABLE, repository, requested_ref, exc)
        if not FULL_COMMIT_SHA.fullmatch(sha):
            detail = f"GitHub answered with {sha!r}, which is not a full commit sha"
            return _unresolved(UnresolvedReason.UNAVAILABLE, repository, requested_ref, detail)
        return ResolvedRevision(sha)


def _reason_for(exc: GitHubAppError) -> UnresolvedReason:
    """What a GitHub answer means for the ref.

    A rate limit comes back as a 403 too, so it is checked first: it is
    retryable, never "no access".
    """
    from syn_adapters.github.client import GitHubRateLimitError

    if isinstance(exc, GitHubRateLimitError):
        return UnresolvedReason.UNAVAILABLE
    if exc.status_code in _NOT_FOUND_STATUSES:
        return UnresolvedReason.NOT_FOUND
    if exc.status_code in _NO_ACCESS_STATUSES:
        return UnresolvedReason.NO_ACCESS
    return UnresolvedReason.UNAVAILABLE


def _unresolved(
    reason: UnresolvedReason,
    repository: RepositoryRef,
    requested_ref: str,
    cause: Exception | str,
) -> UnresolvedRevision:
    logger.warning(
        "Could not resolve %s@%s (%s): %s", repository.slug, requested_ref, reason.value, cause
    )
    return UnresolvedRevision(reason, str(cause))
