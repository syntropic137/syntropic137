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
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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


async def fork(execution_id: str, request: ForkRequest) -> ForkResponse:
    """Admit a fork of ``execution_id``, or raise why not.

    The refusals are the parent's own (`fork_rules.refuse_fork`): a status that
    may not be forked, a cancel without an override, a started phase whose
    effects are unacknowledged, a parent already forked. They surface as 409,
    because each is a conflict with the parent's recorded state rather than a
    malformed request.
    """
    from syn_api._wiring import get_workflow_execution_repository

    # Through the context's public API, not its internal subpaths: a deep
    # import here is what `test_cross_context_public_api` forbids.
    from syn_domain.contexts.orchestration import (
        ExecutionForkedEvent,
        ForkExecutionCommand,
    )

    executions = get_workflow_execution_repository()
    parent = await executions.get_by_id(execution_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"No execution {execution_id}")

    child_id = f"exec-{uuid4().hex[:12]}"
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

    await executions.save(parent)
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
