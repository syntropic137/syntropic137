"""Put an execution in an eval, take it out, and set a workflow's default eval (#967).

``POST /executions/{id}/eval`` attaches a run to an eval after the fact, in any
status; it records ``association_kind = attached`` and never copies a baseline.
``DELETE /executions/{id}/eval?eval_id=`` detaches it, naming the eval so a
stale caller cannot detach a run from an eval it has since moved to. The
eval is named in the query, like ``?tag=`` on the tag routes, because a DELETE
body has no defined meaning in HTTP.

Membership lives on the EXECUTION aggregate. Whether the eval can take a run
is decided by loading the Eval aggregate, never a read model: the eval
projection lags the store. So every response here is the aggregate's state
after the edit, and an eval id is used exactly as typed, never prefix-expanded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from syn_adapters.projection_stores.prefix_match import format_ambiguous_error, resolve_by_prefix
from syn_api._wiring import (
    ensure_connected,
    get_eval_repo,
    get_projection_mgr,
    get_publisher,
    get_workflow_execution_repository,
    get_workflow_repo,
    sync_published_events_to_projections,
)
from syn_api.types import (
    AttachEvalRequest,
    ExecutionEvalResponse,
    SetDefaultEvalRequest,
    WorkflowDefaultEvalResponse,
)
from syn_domain.contexts.orchestration import (
    AttachExecutionToEvalCommand,
    AttachExecutionToEvalHandler,
    DetachExecutionFromEvalCommand,
    DetachExecutionFromEvalHandler,
    EvalId,
    EvalUnavailableError,
    SetWorkflowDefaultEvalCommand,
    SetWorkflowDefaultEvalHandler,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import EvalMembershipResult

router = APIRouter(tags=["evals"])

_MEMBERSHIP_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {"description": "No execution has this id, or no eval has the eval id"},
    409: {
        "description": (
            "The eval is archived, the run belongs to a different eval, "
            "or the id prefix matches more than one execution"
        )
    },
    422: {"description": "The eval id is not a valid eval id"},
}

_DEFAULT_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {"description": "No workflow has this id, or no eval has the eval id"},
    409: {"description": "The eval is archived, or the id prefix matches more than one workflow"},
    422: {"description": "The eval id is not a valid eval id"},
}

_DETACH_QUERY = Query(
    ...,
    description="The eval to detach from. Must be the eval the run belongs to, or none.",
)


async def _resolve(namespace: str, raw_id: str, entity: str) -> str:
    """Expand an id prefix; a miss falls through so the aggregate decides existence."""
    await ensure_connected()
    match = await resolve_by_prefix(get_projection_mgr().store, namespace, raw_id)
    if match.is_ambiguous:
        raise HTTPException(
            status_code=409, detail=format_ambiguous_error(entity, raw_id, match.candidates)
        )
    return match.full_id or raw_id


def _unavailable(exc: EvalUnavailableError) -> HTTPException:
    """404 for an eval that does not exist, 409 for one that is archived."""
    return HTTPException(status_code=404 if exc.missing else 409, detail=str(exc))


def _eval_id(raw: str) -> EvalId:
    try:
        return EvalId(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc


async def _membership(
    result: EvalMembershipResult | None, execution_id: str
) -> ExecutionEvalResponse:
    """The membership an edit left, or the HTTP error naming why there is none."""
    if result is None:
        raise HTTPException(status_code=404, detail=f"Execution not found: {execution_id}")
    if not result.success or result.membership is None:
        raise HTTPException(status_code=409, detail=result.error)
    await sync_published_events_to_projections()
    membership = result.membership
    kind = membership.association_kind
    return ExecutionEvalResponse(
        execution_id=execution_id,
        eval_id=membership.eval_id,
        association_kind=kind.value if kind is not None else None,
        launched_eval_id=membership.launched_eval_id,
    )


@router.post(
    "/executions/{execution_id}/eval",
    response_model=ExecutionEvalResponse,
    responses=_MEMBERSHIP_RESPONSES,
)
async def attach_execution_to_eval_endpoint(
    execution_id: str, body: AttachEvalRequest
) -> ExecutionEvalResponse:
    """Attach an execution to an eval, in any status. Never copies the eval's baseline."""
    execution_id = await _resolve("workflow_execution_details", execution_id, "Execution")
    handler = AttachExecutionToEvalHandler(
        get_workflow_execution_repository(), get_eval_repo(), get_publisher()
    )
    try:
        result = await handler.handle(
            AttachExecutionToEvalCommand(aggregate_id=execution_id, eval_id=body.eval_id)
        )
    except EvalUnavailableError as exc:
        raise _unavailable(exc) from exc
    return await _membership(result, execution_id)


@router.delete(
    "/executions/{execution_id}/eval",
    response_model=ExecutionEvalResponse,
    responses=_MEMBERSHIP_RESPONSES,
)
async def detach_execution_from_eval_endpoint(
    execution_id: str, eval_id: str = _DETACH_QUERY
) -> ExecutionEvalResponse:
    """Detach an execution from its eval. The launch record (`launched_eval_id`) is kept."""
    detach_from = _eval_id(eval_id)
    execution_id = await _resolve("workflow_execution_details", execution_id, "Execution")
    handler = DetachExecutionFromEvalHandler(get_workflow_execution_repository(), get_publisher())
    result = await handler.handle(
        DetachExecutionFromEvalCommand(aggregate_id=execution_id, eval_id=detach_from)
    )
    return await _membership(result, execution_id)


@router.put(
    "/workflows/{workflow_id}/default-eval",
    response_model=WorkflowDefaultEvalResponse,
    responses=_DEFAULT_RESPONSES,
)
async def set_workflow_default_eval_endpoint(
    workflow_id: str, body: SetDefaultEvalRequest
) -> WorkflowDefaultEvalResponse:
    """Set or clear the eval a workflow's runs join when the launch names none."""
    workflow_id = await _resolve("workflow_details", workflow_id, "Workflow")
    handler = SetWorkflowDefaultEvalHandler(get_workflow_repo(), get_eval_repo(), get_publisher())
    try:
        result = await handler.handle(
            SetWorkflowDefaultEvalCommand(aggregate_id=workflow_id, eval_id=body.eval_id)
        )
    except EvalUnavailableError as exc:
        raise _unavailable(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    if not result.success:
        raise HTTPException(status_code=409, detail=result.error)
    await sync_published_events_to_projections()
    default_eval_id = str(body.eval_id) if body.eval_id is not None else None
    return WorkflowDefaultEvalResponse(workflow_id=workflow_id, default_eval_id=default_eval_id)
