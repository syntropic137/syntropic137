"""Value objects of the feedback context (ADR-076-feedback-ticketing).

Every word here is defined in docs/architecture/feedback-ubiquitous-language.md.
None of them carries reporter text: the event store holds ids and hashes only.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TicketType(StrEnum):
    """What a ticket is about. The legacy lib/ui-feedback values, kept so imports map 1:1."""

    BUG = "bug"
    FEATURE = "feature"
    UI_UX = "ui_ux"
    PERFORMANCE = "performance"
    QUESTION = "question"
    OTHER = "other"


class Priority(StrEnum):
    """P0 (critical) to P3 (low). Never low/medium/high/critical."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Screening(StrEnum):
    """Whether a ticket's text may be shown to an agent or a public surface."""

    CLEAN = "clean"
    QUARANTINED = "quarantined"


class PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class ResolutionRule(StrEnum):
    """Which arm of the Resolution Policy resolved a ticket."""

    RELEASED = "released"
    ALL_REPORTERS_OBSERVED = "all_reporters_observed"


class CloseReason(StrEnum):
    WONT_FIX = "wont_fix"
    DUPLICATE_OF = "duplicate_of"
    INVALID = "invalid"
    LEGACY = "legacy"


class TicketStatus(StrEnum):
    """Derived, never stored. See ``derive_status``."""

    QUARANTINED = "quarantined"
    CLOSED = "closed"
    RESOLVED = "resolved"
    IN_PROGRESS = "in_progress"
    FIX_MERGED = "fix_merged"
    OPEN = "open"


class Provenance(BaseModel):
    """Where a submission came from. ``key_id`` is None on the anonymous lane.

    Version and commit are stamped by the Relay's server, never by the browser.
    ``route`` is the UI route path the reporter was on, not anything they typed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str | None
    surface: str = Field(min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=64)
    commit: str | None = Field(default=None, max_length=64)
    route: str | None = Field(default=None, max_length=512)


class PullRequestRef(BaseModel):
    """A pull request, keyed by repository id so a rename cannot split one PR in two."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = Field(min_length=1)
    repository_id: int
    number: int = Field(gt=0)


class PullRequestObservation(BaseModel):
    """The latest state the aggregate has accepted for one linked PR."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: PullRequestState
    observed_at: datetime | None = None


class FixObservation(BaseModel):
    """What one source last reported about the fix in its own deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contains_fix: bool
    version: str
    observed_at: datetime


def derive_status(
    *,
    screening: Screening,
    closed: bool,
    resolved: bool,
    pull_requests: list[PullRequestState],
) -> TicketStatus:
    """A ticket's status, from facts the aggregate already holds.

    An open PR outranks a merged one: a second fix still in flight means the work
    is in progress, and a PR closed then reopened is open again, not merged.
    """
    if screening is Screening.QUARANTINED:
        return TicketStatus.QUARANTINED
    if closed:
        return TicketStatus.CLOSED
    if resolved:
        return TicketStatus.RESOLVED
    if PullRequestState.OPEN in pull_requests:
        return TicketStatus.IN_PROGRESS
    if PullRequestState.MERGED in pull_requests:
        return TicketStatus.FIX_MERGED
    return TicketStatus.OPEN
