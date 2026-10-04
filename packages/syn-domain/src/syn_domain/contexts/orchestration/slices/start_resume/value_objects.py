"""The resume start to-do list's records (ADR-014 s7)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

ResumeStartStatus = Literal["pending", "paused", "retryable", "dispatched", "started", "failed"]

#: Statuses still owed a start.
#:
#: `paused` is reversible, never terminal. `retryable` is a start that failed for
#: a reason that may not recur. `dispatched` is the subtle one: the start was
#: handed to a background task and NOTHING yet proves a child exists. Marking
#: that `started` lost admitted resumes whose process died between spawning the
#: task and writing the child's first event - the parent had admitted a resume, no
#: child stream existed, and the to-do was no longer owed (codex review of
#: #1459). It stays owed until the child's own `WorkflowExecutionStarted` says
#: otherwise; re-offering is safe because `StartResumeHandler.handle` returns early
#: when the child already exists, and the child's id is fixed by the parent's
#: `ExecutionResumed` rather than minted per attempt.
OWED_STATUSES: tuple[ResumeStartStatus, ...] = ("pending", "paused", "retryable", "dispatched")

#: How long a `dispatched` start is left alone before it is re-offered.
#:
#: The window between handing a start to a task and the child's own
#: `WorkflowExecutionStarted` arriving. Re-offering inside it is not harmful in
#: the aggregate - the child's id is fixed and the handler returns early - but it
#: is not free either: each re-offer takes an admission ticket (codex review of
#: #1459). So it waits. A start still queued for an execution-budget slot is
#: never re-offered at all: the starter reports it held (#1557).
DISPATCH_GRACE = timedelta(minutes=5)

#: How many times a start may be attempted before `retryable` becomes `failed`.
#:
#: A CEILING, not a tuning knob. Without one, a resume whose start fails the same
#: way for ever is retried for ever, and each attempt can provision a workspace.
MAX_START_ATTEMPTS = 3


class ResumeStartRecord(BaseModel):
    """One admitted resume on the to-do list, keyed by its PARENT.

    Keyed by the parent because that is the one id every `ExecutionResumed`
    has: under ADR-023 the child's id can replay as None, and the parent
    admits at most one resume.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_execution_id: str
    status: ResumeStartStatus = "pending"
    status_reason: str | None = None
    recorded_at: datetime

    #: When the start was handed to a background task, if it has been. A
    #: `dispatched` record is only re-offered once this is older than
    #: `DISPATCH_GRACE`, so a child that takes a while to write its first event
    #: is not dispatched again on every processor pass.
    dispatched_at: datetime | None = None

    #: Starts attempted so far. Only counted for attempts that failed for a
    #: reason worth retrying: a `paused` hold is not an attempt, because the
    #: gate refused before anything was tried.
    attempts: int = 0


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
