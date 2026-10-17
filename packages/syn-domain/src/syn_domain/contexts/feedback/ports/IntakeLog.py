"""IntakeLog: the purgeable log of raw submissions the Screener works from (ADR-076-feedback-ticketing).

The one place reporter text lives. Everything persisted here is persisted
BEFORE the command it leads to, so a crashed Screener resumes from the row and
never re-decides: the verdict, the allocated ticket id and number, and the
disposition are each written once.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import Provenance  # noqa: TC001
from syn_domain.contexts.feedback.domain.ScreeningPolicy import ScreeningResult  # noqa: TC001


class Disposition(StrEnum):
    """What the Screener decided for one submission."""

    OPEN = "open"
    REPORT = "report"
    EXACT_DUPLICATE = "exact_duplicate"
    QUARANTINE = "quarantine"
    SPAM = "spam"
    FAILED = "failed"


class LeasedSubmission(BaseModel):
    """A submission the caller holds the lease on, with whatever was already decided."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    submission_id: str = Field(min_length=1)
    source_id: str | None
    provenance: Provenance
    raw_text: str
    verdict: ScreeningResult | None
    ticket_id: str | None
    ticket_number: int | None
    disposition: Disposition | None
    lease_expires_at: datetime


class IntakeLog(Protocol):
    async def lease(self, *, limit: int, lease_seconds: int) -> list[LeasedSubmission]: ...

    async def record_verdict(self, submission_id: str, verdict: ScreeningResult) -> None: ...

    async def record_disposition(
        self,
        submission_id: str,
        disposition: Disposition,
        *,
        ticket_id: str | None,
        ticket_number: int | None,
    ) -> None: ...

    async def mark_dispatched(self, submission_id: str) -> None: ...

    async def purge(self, *, older_than: datetime) -> int: ...
