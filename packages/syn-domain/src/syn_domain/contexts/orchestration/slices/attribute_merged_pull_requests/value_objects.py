"""What the merged-PR attribution manager keeps between events (#1728)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

PullRequestStatus = Literal["open", "merged", "closed"]


class PullRequestMergeState(BaseModel):
    """What the forge says about one PR now. ``readable=False``: ask again later."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    readable: bool
    merged_at: datetime | None = None
    closed: bool = False


class PullRequestMergePort(Protocol):
    """Asks the forge whether a PR was merged. MUST NOT raise: unreadable instead."""

    async def read_merge(self, repository: str, pull_request: int) -> PullRequestMergeState: ...


class MergeRecorder(Protocol):
    """Records ``PullRequestMergeRecorded`` on one execution through its aggregate."""

    async def record_merge(
        self, execution_id: str, repository: str, pull_request: int, merged_at: datetime
    ) -> None: ...


class RunLinks(BaseModel):
    """One execution's resume chain, oldest first, and the PRs it is linked to.

    ``repositories`` are the run's ``owner/name`` slugs, which is how a branch
    observation's directory name is resolved to the PR's repository.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    chain: tuple[str, ...]
    pull_requests: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()


class PullRequestContributors(BaseModel):
    """One PR and every execution that contributed to it.

    ``recorded`` is the executions whose merge is already on their stream, so
    a live pass records each contributor once, however often it is offered.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    pull_request: int
    execution_ids: tuple[str, ...] = ()
    status: PullRequestStatus = "open"
    merged_at: datetime | None = None
    recorded: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return pull_request_key(self.repository, self.pull_request)

    def with_contributors(self, execution_ids: tuple[str, ...]) -> PullRequestContributors:
        merged = tuple(dict.fromkeys((*self.execution_ids, *execution_ids)))
        return self.model_copy(update={"execution_ids": merged})

    @property
    def unrecorded(self) -> tuple[str, ...]:
        return tuple(e for e in self.execution_ids if e not in self.recorded)


def pull_request_key(repository: str, pull_request: int) -> str:
    return f"{repository}#{pull_request}"
