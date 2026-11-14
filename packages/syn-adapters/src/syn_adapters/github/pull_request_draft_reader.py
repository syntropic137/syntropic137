"""GitHub adapter for ``PullRequestDraftPort`` (#2058).

Reads ``GET /repos/{slug}/pulls/{number}`` through the App installation that
covers the repository. Total, as the port requires: every failure is logged
and becomes ``UNKNOWN`` with the reason, which the trigger evaluator treats as
"do not fire".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.github.ports import (
    PullRequestDraftPort,
    PullRequestDraftReading,
    PullRequestReadiness,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)


class _Pull(BaseModel):
    model_config = ConfigDict(extra="ignore")
    draft: bool


class GitHubPullRequestDraftReader(PullRequestDraftPort):
    """Reads a pull request's draft flag from GitHub.

    Takes a client FACTORY, like ``GitHubRemoteBranchReader``: a server
    without a configured App answers ``UNKNOWN`` instead of failing to start.
    """

    def __init__(self, client_factory: Callable[[], GitHubAppClient]) -> None:
        self._client_factory = client_factory

    async def read_draft_state(
        self,
        repository: str,
        pr_number: int,
        installation_id: str,
    ) -> PullRequestDraftReading:
        """Whether PR ``pr_number`` of ``repository`` is a draft, or why that is unknown."""
        from syn_adapters.github.client import GitHubAppError

        try:
            client = self._client_factory()
            installation = installation_id or await client.get_installation_for_repo(repository)
            data = await client.api_get(f"/repos/{repository}/pulls/{pr_number}", installation)
            pull = _Pull.model_validate(data)
        except (GitHubAppError, httpx.HTTPError, ValueError, ValidationError) as exc:
            logger.warning(
                "Could not read draft state of %s#%d: %s", repository, pr_number, exc
            )
            return PullRequestDraftReading(
                readiness=PullRequestReadiness.UNKNOWN,
                detail=f"{type(exc).__name__}: {exc}",
            )
        if pull.draft:
            return PullRequestDraftReading(readiness=PullRequestReadiness.DRAFT)
        return PullRequestDraftReading(readiness=PullRequestReadiness.READY)
