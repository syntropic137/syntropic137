"""The resume start to-do list's records (ADR-014 s7).

The record rules - statuses, grace, attempt ceiling - are the start to-do
list's, shared with direct execution requests (#1557), and re-exported here
under the names this slice has always used.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.orchestration._shared.start_record import StartRecord, StartStatus
from syn_domain.contexts.orchestration._shared.start_todo import (
    DISPATCH_GRACE,
    MAX_START_ATTEMPTS,
    OWED_STATUSES,
)

logger = logging.getLogger(__name__)

ResumeStartStatus = StartStatus

__all__ = [
    "DISPATCH_GRACE",
    "MAX_START_ATTEMPTS",
    "OWED_STATUSES",
    "ResumeChild",
    "ResumeStartRecord",
    "ResumeStartStatus",
    "read_record",
]


class ResumeStartRecord(StartRecord):
    """One admitted resume on the to-do list, keyed by its PARENT.

    Keyed by the parent because that is the one id every `ExecutionResumed`
    has: under ADR-023 the child's id can replay as None, and the parent
    admits at most one resume.
    """

    parent_execution_id: str

    @property
    def key(self) -> str:
        return self.parent_execution_id


class ResumeChild(BaseModel):
    """The execution a resume start will create, named before it exists (#1557).

    Returned by `StartResumeHandler.validate` so the dispatcher can queue the
    start under the child's own id: that is what `syn execution show <child>`
    looks up, and it answers `queued` instead of 404 while the start waits.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    workflow_id: str


def read_record(row: object) -> ResumeStartRecord | None:
    """A stored row as a record, or None - logged - when it cannot be read."""
    try:
        return ResumeStartRecord.model_validate(row)
    except ValidationError:
        logger.warning("Unreadable resume start record skipped: %r", row)
        return None
