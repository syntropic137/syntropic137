"""Tell an execution's stream that one of its workspaces was kept, and why (#2321).

THE KEEP COMES FIRST. A guard that could not prove a workspace's work safe has
already decided to keep its directory, and nothing here may undo that: this
only records the decision. So `record` never raises. A store that is down, an
execution with no stream, an aggregate that refuses - each is logged and the
directory stays, which costs only disk. The stale-directory reclaimer keeps a
directory again on every pass, so a record lost to a failure is offered again
on the next one, and the aggregate turns every repeat into no event.

Only the reasons that say the work is unproven (`WORK_UNPROVEN`) are
recorded. A workspace still mounted or not yet settled is not retained work,
and recording it would put a clock's worth of noise on the stream.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordWorkspaceRetainedCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.workspace_retention import (
    WORK_UNPROVEN,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
        WorkflowExecutionRepositoryPort,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.orphaned_workspace import (
        Retained,
    )

logger = logging.getLogger(__name__)


class RetainedWorkspaceRecorder:
    """Puts a kept workspace on its execution's stream. Never raises."""

    def __init__(self, repository: Callable[[], WorkflowExecutionRepositoryPort]) -> None:
        #: Resolved per record, inside the failure boundary: opening the store
        #: is one of the things that can fail.
        self._repository = repository

    async def record(self, execution_id: str, workspace_id: str, retained: Retained) -> None:
        """Record ``retained`` on ``execution_id`` when it says the work is unproven."""
        if retained.reason not in WORK_UNPROVEN:
            return
        command = RecordWorkspaceRetainedCommand(
            execution_id, workspace_id, retained.reason, retained.detail
        )
        try:
            repository = self._repository()
            aggregate = await repository.get_by_id(execution_id)
            if aggregate is None:
                logger.warning(
                    "Workspace %s was kept (%s) but execution %s has no stream to record it on",
                    workspace_id,
                    retained.reason.value,
                    execution_id,
                )
                return
            aggregate.record_workspace_retained(command)
            await repository.save(aggregate)
        except Exception:
            logger.exception(
                "Could not record that workspace %s of execution %s was kept (%s); "
                "its directory stays regardless",
                workspace_id,
                execution_id,
                retained.reason.value,
            )
