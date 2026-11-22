"""The failure streak of one workflow template, and the event fields it reads (#1569)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)

RECENT_EXECUTIONS_KEPT = 50
"""How many execution ids a streak remembers. ``length`` stays exact past it."""


class FailureStreak(BaseModel):
    """The unbroken run of streak-extending failures a template has had since it last completed.

    ``length`` is exact. ``execution_ids`` holds the most recent
    ``RECENT_EXECUTIONS_KEPT`` of them, oldest first, so a streak of 29 lists
    all 29 and a streak of 500 lists the last 50. A template with no streak,
    including one this projection has never seen, has ``length == 0``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    length: int = 0
    execution_ids: tuple[str, ...] = ()
    first_failed_at: datetime | None = None
    last_failed_at: datetime | None = None

    def extended_by(self, execution_id: str, failed_at: datetime | None) -> FailureStreak:
        """This streak with one more failed execution on the end.

        Already counted means unchanged: a re-delivered WorkflowFailed must not
        lengthen the streak. An execution fails at most once, so this is the
        only way the same id can arrive twice. The check reads the kept ids, so
        a duplicate older than the last ``RECENT_EXECUTIONS_KEPT`` failures
        would count again. That cannot happen: the aggregate fails only a
        RUNNING execution and never returns it to RUNNING, the store rejects a
        stale append, and the coordinator skips events at or before a
        projection's checkpoint position, so a redelivery never reaches here.
        """
        if execution_id in self.execution_ids:
            return self
        return self.model_copy(
            update={
                "length": self.length + 1,
                "execution_ids": (*self.execution_ids, execution_id)[-RECENT_EXECUTIONS_KEPT:],
                "first_failed_at": self.first_failed_at or failed_at,
                "last_failed_at": failed_at or self.last_failed_at,
            }
        )


class WorkflowFailedRef(BaseModel):
    """The fields a streak needs from a WorkflowFailed payload.

    Not WorkflowFailedEvent itself: every other field is ignored rather than
    validated, so a stored payload missing one this read model never uses
    still counts. The classification goes through
    ``FailureClassification.from_stored``, the one coercion point, so a member
    this reader has never heard of reads as UNCLASSIFIED instead of failing the
    replay.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    workflow_id: str = ""
    execution_id: str = ""
    failed_at: datetime | None = None
    failure_classification: Annotated[
        FailureClassification, BeforeValidator(FailureClassification.from_stored)
    ] = FailureClassification.UNCLASSIFIED


class WorkflowCompletedRef(BaseModel):
    """The one field a streak needs from a WorkflowCompleted payload."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    workflow_id: str = ""
