"""Pushes an execution's phases recorded (#1544).

`PhaseCommitPushed` is what a resume reads to tell its own unverified commits
from somebody else's (PC-128), but nothing served it: answering "did this run
record its pushes, from which phase, at which SHA" meant querying the event
store by hand. Read from the aggregate, so it is the same replay a resume does.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from syn_api.routes.executions.control import _resolve_execution_id
from syn_api.types import ExecutionPushesResponse, RecordedPush

logger = logging.getLogger(__name__)

router = APIRouter(tags=["executions"])


@router.get("/executions/{execution_id}/pushes", response_model=ExecutionPushesResponse)
async def get_execution_pushes_endpoint(execution_id: str) -> ExecutionPushesResponse:
    """Every `PhaseCommitPushed` recorded on the execution: phase, repository, branch, SHA."""
    from syn_api._wiring import get_workflow_execution_repository

    try:
        execution_id = await _resolve_execution_id(execution_id)
        aggregate = await get_workflow_execution_repository().get_by_id(execution_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("could not read execution %s", execution_id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not read execution {execution_id}: the event store could not be "
                f"read ({type(exc).__name__}). This is not a statement that it recorded no pushes."
            ),
        ) from exc
    if aggregate is None:
        raise HTTPException(status_code=404, detail=f"No execution {execution_id}")
    return ExecutionPushesResponse(
        execution_id=execution_id,
        pushes=[
            RecordedPush(phase_id=p.phase_id, repository=p.repository, branch=p.branch, sha=p.sha)
            for p in aggregate.pushed_commits
        ],
    )
