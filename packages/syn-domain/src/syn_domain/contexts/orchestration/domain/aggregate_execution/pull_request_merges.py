"""The merged PRs an execution contributed to (#1728).

Kept beside the aggregate rather than in it: a fact about the PR, recorded on
each contributor once, with no bearing on the run's lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    merge_recorded_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordPullRequestMergeCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.PullRequestMergeRecordedEvent import (
        PullRequestMergeRecordedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,  # noqa: F401 - the generic parameter below names it
    )


class PullRequestMergeRecording(AggregateRoot["WorkflowExecutionStartedEvent"]):
    """Records ``PullRequestMergeRecorded`` once per PR on a ``WorkflowExecutionAggregate``."""

    _workflow_id: str | None
    #: `owner/name#number` of every merged PR this run is recorded against.
    _merged_pull_requests: frozenset[str] = frozenset()

    @command_handler("RecordPullRequestMergeCommand")
    def record_pull_request_merge(self, command: RecordPullRequestMergeCommand) -> None:
        """Record that this run contributed to a merged PR. Already recorded, no event."""
        if self.id is None:
            msg = "Execution does not exist"
            raise ValueError(msg)
        if f"{command.repository}#{command.pull_request}" in self._merged_pull_requests:
            return
        self._apply(merge_recorded_event(command, self._workflow_id or ""))

    @event_sourcing_handler("PullRequestMergeRecorded")
    def on_pull_request_merge_recorded(self, event: PullRequestMergeRecordedEvent) -> None:
        """Apply PullRequestMergeRecordedEvent. A fact about the PR, recorded once."""
        key = f"{evt(event, 'repository')}#{evt(event, 'pull_request')}"
        self._merged_pull_requests = self._merged_pull_requests | {key}


__all__ = ["PullRequestMergeRecording"]
