"""ForgeReads: what feedback reads from the forge to resolve a ticket (ADR-076-feedback-ticketing, #1628)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import (  # noqa: TC001
    PullRequestRef,
    PullRequestState,
)


class PullRequestSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: PullRequestState
    merge_commit: str | None
    observed_at: datetime


class PublishedRelease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str = Field(min_length=1)
    version: str = Field(min_length=1)
    commit: str = Field(min_length=1)


class ForgeReads(Protocol):
    async def pull_request(self, ref: PullRequestRef) -> PullRequestSnapshot: ...

    async def contains_commit(self, repository: str, *, base: str, commit: str) -> bool:
        """True when ``commit`` is an ancestor of (or equal to) ``base``."""
        ...

    async def releases_since(
        self, repository: str, *, since: datetime
    ) -> list[PublishedRelease]: ...
