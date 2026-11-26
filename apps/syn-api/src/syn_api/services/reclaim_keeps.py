"""Put the stale-directory reclaimer's keeps on their executions' streams (#2321).

The reclaimer is the workspace janitor, and the janitor never reaches run
history (owner decision, #1983). So it only reports each pass, and this, built
outside it, records what the pass kept through `RetainedWorkspaceRecorder`:
a keep the reclaimer made before it knew the owner names no execution and is
not recorded. The recorder records only work it could not prove safe, never
raises, and a keep the next pass makes again adds no event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import Retained, RetainedWorkspaceRecorder

if TYPE_CHECKING:
    from syn_api.services.workspace_dir_reclaim import PassObserver, ReclaimPass


def record_reclaim_keeps(recorder: RetainedWorkspaceRecorder | None = None) -> PassObserver:
    """The observer that records each pass's owned keeps, on the event store by default."""
    if recorder is None:
        from syn_adapters.storage.repositories import get_workflow_execution_repository

        recorder = RetainedWorkspaceRecorder(get_workflow_execution_repository)
    keeps = recorder

    async def on_pass(result: ReclaimPass, /) -> None:
        for kept in result.retained:
            if kept.execution_id is not None:
                await keeps.record(
                    kept.execution_id, kept.workspace_id, Retained(kept.reason, kept.detail)
                )

    return on_pass
