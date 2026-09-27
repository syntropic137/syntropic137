"""Forking a terminal execution into a new one (ADR-014 s7).

Separate from `control.py` on purpose: pause, resume and cancel act on the run
you name, while a fork CREATES a second run. `resume` there is the pause/resume
pair and has nothing to do with resuming a failed execution - that is this.

The endpoint is thin, as the API is meant to be. It resolves the parent, hands
the parent aggregate a `ForkExecutionCommand` and saves; recording
`ExecutionForked` is what puts the start on the fork to-do list, and the
`ForkStartProcessManager` starts the child. Nothing here runs a workflow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import WorkflowExecutionRepositoryPort

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fork"])


class ForkRequest(BaseModel):
    """What an operator must decide before a fork is admitted.

    Both flags default to the REFUSAL, because both exist to make an operator
    say something out loud. Neither implies the other.
    """

    model_config = ConfigDict(extra="forbid")

    override_cancellation: bool = Field(
        default=False,
        description=(
            "Fork a CANCELLED parent. A cancel is an instruction to stop, so "
            "forking past it needs a fresh decision rather than inheriting the "
            "old one."
        ),
    )
    acknowledge_external_effects: bool = Field(
        default=False,
        description=(
            "Accept that the phase the fork restarts may already have pushed or "
            "published something in the parent, which re-running it repeats."
        ),
    )


class ForkResponse(BaseModel):
    """The fork that was admitted, and what the child will do."""

    parent_execution_id: str
    execution_id: str
    """The CHILD's id - the run to watch from here on."""
    resume_phase_id: str
    """The phase the child restarts, from its beginning."""
    inherited_phase_ids: list[str]
    """Completed phases the child will NOT re-run."""
    cancellation_overridden: bool
    external_effects_acknowledged: bool


async def _free_child_id(executions: WorkflowExecutionRepositoryPort, attempts: int = 5) -> str:
    """An execution id nothing else is using.

    48 random bits rarely collide, but the consequence of one is bad enough to be
    worth a lookup: the parent's single fork would be spent naming an execution
    that already exists, and child start would see that stream and treat the fork
    as already started - so the caller gets a success pointing at an unrelated
    run (codex review of #1461).
    """
    for _ in range(attempts):
        candidate = f"exec-{uuid4().hex[:12]}"
        if not await executions.exists(candidate):
            return candidate
    msg = "Could not mint an unused execution id for the fork"
    raise HTTPException(status_code=503, detail=msg)


async def fork(execution_id: str, request: ForkRequest) -> ForkResponse:
    """Admit a fork of ``execution_id``, or raise why not.

    The refusals are the parent's own (`fork_rules.refuse_fork`) plus the
    child's (`fork_start.refuse_fork_start`), and BOTH are checked before
    anything is written. A parent admits exactly one fork, so recording an
    admission the child cannot act on would spend that one fork on a run that
    never starts - the caller would be told yes and get nothing.

    They surface as 409, because each is a conflict with the parent's recorded
    state rather than a malformed request.
    """
    from event_sourcing import ConcurrencyConflictError

    from syn_api._wiring import get_workflow_execution_repository
    from syn_domain.contexts.orchestration import (
        ExecutionForkedEvent,
        ForkExecutionCommand,
        refuse_fork_start,
    )

    executions = get_workflow_execution_repository()
    parent = await executions.get_by_id(execution_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"No execution {execution_id}")

    child_id = await _free_child_id(executions)
    try:
        parent.fork_execution(
            ForkExecutionCommand(
                execution_id=execution_id,
                fork_execution_id=child_id,
                override_cancellation=request.override_cancellation,
                acknowledge_external_effects=request.acknowledge_external_effects,
            )
        )
    except ValueError as exc:
        # The parent's decision, not a bad request: 409.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    forked = next(
        (
            e.event
            for e in parent.get_uncommitted_events()
            if isinstance(e.event, ExecutionForkedEvent)
        ),
        None,
    )
    if forked is None:  # pragma: no cover - the handler emits it or raises
        raise HTTPException(status_code=500, detail="The fork was admitted but not recorded")

    # STILL UNCOMMITTED here, which is the point: the child's own refusal is
    # checked against the aggregate in memory, so a fork the child could not
    # start is never written and the parent's one fork is not spent on it.
    start_refusal = refuse_fork_start(parent.fork_start_command())
    if start_refusal is not None:
        raise HTTPException(status_code=409, detail=start_refusal)

    try:
        await executions.save(parent)
    except ConcurrencyConflictError as exc:
        # Another request forked this parent between our load and our save. The
        # store refused the second write, so there is exactly one fork - but the
        # caller needs to be told which, not handed a 500.
        current = await executions.get_by_id(execution_id)
        existing = current.fork_execution_id if current is not None else None
        detail = f"Execution {execution_id} was forked concurrently" + (
            f" as {existing}" if existing else ""
        )
        raise HTTPException(status_code=409, detail=detail) from exc

    logger.info(
        "Fork of %s admitted as %s, resuming at %s",
        execution_id,
        child_id,
        forked.resume_phase_id,
    )
    return ForkResponse(
        parent_execution_id=execution_id,
        execution_id=child_id,
        resume_phase_id=forked.resume_phase_id,
        inherited_phase_ids=[p.phase_id for p in forked.inherited_phases],
        cancellation_overridden=forked.cancellation_overridden,
        external_effects_acknowledged=forked.external_effects_acknowledged,
    )


@router.post("/executions/{execution_id}/fork", response_model=ForkResponse)
async def fork_execution_endpoint(
    execution_id: str,
    request: ForkRequest | None = None,
) -> ForkResponse:
    """Fork a failed or interrupted execution so it resumes where it stopped."""
    from syn_api.routes.executions.control import _resolve_execution_id

    execution_id = await _resolve_execution_id(execution_id)
    return await fork(execution_id, request or ForkRequest())
