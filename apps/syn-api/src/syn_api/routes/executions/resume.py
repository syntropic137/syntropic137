"""Resuming a terminal execution into a new one (ADR-014 s7).

Separate from `control.py` on purpose: cancel and inject act on the run you
name, while a resume CREATES a second run. Until 2026-09-29 `resume` meant
un-pausing, which was deleted because nothing ever read the pause signal; the
name now means only this.

The endpoint is thin, as the API is meant to be. It resolves the parent, hands
the parent aggregate a `ResumeExecutionCommand` and saves; recording
`ExecutionResumed` is what puts the start on the resume to-do list, and the
`ResumeStartProcessManager` starts the child. Nothing here runs a workflow.
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

router = APIRouter(tags=["resume"])


class ResumeRequest(BaseModel):
    """What an operator must decide before a resume is admitted.

    Both flags default to the REFUSAL, because both exist to make an operator
    say something out loud. Neither implies the other.
    """

    model_config = ConfigDict(extra="forbid")

    override_cancellation: bool = Field(
        default=False,
        description=(
            "Resume a CANCELLED parent. A cancel is an instruction to stop, so "
            "resuming past it needs a fresh decision rather than inheriting the "
            "old one."
        ),
    )
    acknowledge_external_effects: bool = Field(
        default=False,
        description=(
            "Accept that the phase the resume restarts may already have pushed or "
            "published something in the parent, which re-running it repeats."
        ),
    )


class ResumeResponse(BaseModel):
    """The resume that was admitted, and what the child will do."""

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
    worth a lookup: the parent's single resume would be spent naming an execution
    that already exists, and child start would see that stream and treat the resume
    as already started - so the caller gets a success pointing at an unrelated
    run (codex review of #1461).
    """
    for _ in range(attempts):
        candidate = f"exec-{uuid4().hex[:12]}"
        if not await executions.exists(candidate):
            return candidate
    msg = "Could not mint an unused execution id for the resume"
    raise HTTPException(status_code=503, detail=msg)


async def resume(execution_id: str, request: ResumeRequest) -> ResumeResponse:
    """Admit a resume of ``execution_id``, or raise why not.

    The refusals are the parent's own (`resume_rules.refuse_resume`) and the child's
    two - the pinned snapshot (`resume_start.refuse_resume_start`) and whether the
    inheritance can actually be read - and ALL of them are checked before
    anything is written. A parent admits exactly one resume, so recording an
    admission the child cannot act on would spend that one resume on a run that
    never starts - the caller would be told yes and get nothing.

    They surface as 409, because each is a conflict with the parent's recorded
    state rather than a malformed request.
    """
    from event_sourcing import ConcurrencyConflictError

    from syn_api._wiring import get_artifact_query, get_workflow_execution_repository
    from syn_domain.contexts.orchestration import (
        ExecutionResumedEvent,
        InheritanceUnavailableError,
        ResumeExecutionCommand,
        inherited_outputs,
        refuse_resume_start,
    )

    executions = get_workflow_execution_repository()
    parent = await executions.get_by_id(execution_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"No execution {execution_id}")

    child_id = await _free_child_id(executions)
    try:
        parent.resume_execution(
            ResumeExecutionCommand(
                execution_id=execution_id,
                resume_execution_id=child_id,
                override_cancellation=request.override_cancellation,
                acknowledge_external_effects=request.acknowledge_external_effects,
            )
        )
    except ValueError as exc:
        # The parent's decision, not a bad request: 409.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    resumed = next(
        (
            e.event
            for e in parent.get_uncommitted_events()
            if isinstance(e.event, ExecutionResumedEvent)
        ),
        None,
    )
    if resumed is None:  # pragma: no cover - the handler emits it or raises
        raise HTTPException(status_code=500, detail="The resume was admitted but not recorded")

    # STILL UNCOMMITTED here, which is the point: the child's refusals are
    # checked against the aggregate in memory, so a resume the child could not
    # start is never written and the parent's one resume is not spent on it.
    #
    # BOTH of the child's start-time refusals, not one. `refuse_resume_start`
    # compares the inheritance against the pinned snapshot; resolving the
    # inheritance is a separate question - the artifacts may be gone, expired or
    # briefly unreachable - and checking only the first admitted a 200 for a resume
    # that could never start, spending the parent's single resume for good.
    command = parent.resume_start_command()
    start_refusal = refuse_resume_start(command)
    if start_refusal is not None:
        raise HTTPException(status_code=409, detail=start_refusal)
    try:
        await inherited_outputs(get_artifact_query(), command.resumed_from)
    except InheritanceUnavailableError as exc:
        # The artifacts the resumed phase would read cannot be handed over. A
        # conflict with recorded state, like every other refusal here.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        await executions.save(parent)
    except ConcurrencyConflictError as exc:
        # Another request resumed this parent between our load and our save. The
        # store refused the second write, so there is exactly one resume - but the
        # caller needs to be told which, not handed a 500.
        current = await executions.get_by_id(execution_id)
        existing = current.resume_execution_id if current is not None else None
        detail = f"Execution {execution_id} was resumed concurrently" + (
            f" as {existing}" if existing else ""
        )
        raise HTTPException(status_code=409, detail=detail) from exc

    logger.info(
        "Resume of %s admitted as %s, resuming at %s",
        execution_id,
        child_id,
        resumed.resume_phase_id,
    )
    return ResumeResponse(
        parent_execution_id=execution_id,
        execution_id=child_id,
        resume_phase_id=resumed.resume_phase_id,
        inherited_phase_ids=[p.phase_id for p in resumed.inherited_phases],
        cancellation_overridden=resumed.cancellation_overridden,
        external_effects_acknowledged=resumed.external_effects_acknowledged,
    )


@router.post("/executions/{execution_id}/resume", response_model=ResumeResponse)
async def resume_execution_endpoint(
    execution_id: str,
    request: ResumeRequest | None = None,
) -> ResumeResponse:
    """Resume a failed or interrupted execution so it resumes where it stopped."""
    from syn_api.routes.executions.control import _resolve_execution_id

    execution_id = await _resolve_execution_id(execution_id)
    return await resume(execution_id, request or ResumeRequest())
