"""GitHub adapter for ``PullRequestMergePort`` (#1728).

Reads ``GET /repos/{slug}/pulls/{number}`` through the App installation that
covers the repository, with the client's token-mint and transport retries.
Total, as the port requires: every failure is logged and becomes
``readable=False``, which the attribution manager asks again on its next pass.
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.orchestration.slices.attribute_merged_pull_requests import (
    PullRequestMergePort,
    PullRequestMergeState,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)


class _Pull(BaseModel):
    model_config = ConfigDict(extra="ignore")
    state: str
    merged_at: datetime | None = None


class GitHubPullRequestMergeReader(PullRequestMergePort):
    """Reads whether a PR was merged, and when, from GitHub."""

    def __init__(self, client_factory: Callable[[], GitHubAppClient]) -> None:
        self._client_factory = client_factory

    async def read_merge(self, repository: str, pull_request: int) -> PullRequestMergeState:
        from syn_adapters.github.client import GitHubAppError

        try:
            client = self._client_factory()
            installation_id = await client.get_installation_for_repo(repository)
            body = await client.api_get(
                f"/repos/{repository}/pulls/{pull_request}", installation_id
            )
            pull = _Pull.model_validate(body)
        except (GitHubAppError, httpx.HTTPError, ValueError, ValidationError) as exc:
            logger.warning("Could not read PR #%s of %s: %s", pull_request, repository, exc)
            return PullRequestMergeState(readable=False)
        return PullRequestMergeState(
            readable=True, merged_at=pull.merged_at, closed=pull.state == "closed"
        )
