"""The record every start to-do list keeps, whatever admitted the start (#1557)."""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - Pydantic resolves it at runtime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

StartStatus = Literal[
    "pending", "paused", "retryable", "dispatched", "started", "failed", "withdrawn"
]


class StartRecord(BaseModel):
    """What every start to-do record holds, whatever admitted the start."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: StartStatus = "pending"
    status_reason: str | None = None
    recorded_at: datetime

    #: When the start was handed to a background task, if it has been. A
    #: `dispatched` record is only re-offered once this is older than
    #: `DISPATCH_GRACE`.
    dispatched_at: datetime | None = None

    #: Starts attempted so far. Only counted for attempts that failed for a
    #: reason worth retrying: a `paused` hold is not an attempt.
    attempts: int = 0

    @property
    def key(self) -> str:
        """The id the record is stored under."""
        raise NotImplementedError


def read_start_record[R: StartRecord](record_type: type[R], row: object) -> R | None:
    """A stored row as a record, or None - logged - when it cannot be read."""
    try:
        return record_type.model_validate(row)
    except ValidationError:
        logger.warning("Unreadable %s skipped: %r", record_type.__name__, row)
        return None
