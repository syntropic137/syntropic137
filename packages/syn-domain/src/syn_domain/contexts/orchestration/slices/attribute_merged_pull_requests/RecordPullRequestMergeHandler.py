"""RecordPullRequestMerge handler (#1728): the aggregate decides, this saves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPullRequestMergeCommand,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.repository import Repository


class RecordPullRequestMergeHandler:
    """Satisfies ``MergeRecorder`` through the execution aggregate."""

    def __init__(self, repository: Repository[WorkflowExecutionAggregate]) -> None:
        self._repository = repository

    async def record_merge(
        self, execution_id: str, repository: str, pull_request: int, merged_at: datetime
    ) -> None:
        execution = await self._repository.get_by_id(execution_id)
        if execution is None:
            msg = f"Execution {execution_id} not found"
            raise ValueError(msg)
        execution.record_pull_request_merge(
            RecordPullRequestMergeCommand(execution_id, repository, pull_request, merged_at)
        )
        await self._repository.save(execution)
