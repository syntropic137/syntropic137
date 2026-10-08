"""PullRequestMergeRecorded event (#1728)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("PullRequestMergeRecorded", "v1")
class PullRequestMergeRecordedEvent(DomainEvent):
    """This execution contributed to a pull request that the forge says was merged.

    One event per contributing execution: a failed run, its resume and an
    independent reverify of the same PR each record their own. The scorecard
    folds them into one merged PR whose cost is every contributor's. Recorded
    by ``MergedPullRequestAttributionProcessManager``, live only, so a replay
    reads this fact and never asks GitHub again.
    """

    execution_id: str
    workflow_id: str
    repository: str
    """``owner/name``."""
    pull_request: int
    merged_at: datetime
