"""The fork start to-do list's records (ADR-014 s7)."""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - pydantic resolves the annotation at runtime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

ForkStartStatus = Literal["pending", "paused", "started", "failed"]

#: Statuses still owed a start. `paused` is reversible, never terminal.
OWED_STATUSES: tuple[ForkStartStatus, ...] = ("pending", "paused")


class ForkStartRecord(BaseModel):
    """One admitted fork on the to-do list, keyed by its PARENT.

    Keyed by the parent because that is the one id every `ExecutionForked`
    has: under ADR-023 the child's id can replay as None, and the parent
    admits at most one fork.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_execution_id: str
    status: ForkStartStatus = "pending"
    status_reason: str | None = None
    recorded_at: datetime


def read_record(row: object) -> ForkStartRecord | None:
    """A stored row as a record, or None - logged - when it cannot be read."""
    try:
        return ForkStartRecord.model_validate(row)
    except ValidationError:
        logger.warning("Unreadable fork start record skipped: %r", row)
        return None
