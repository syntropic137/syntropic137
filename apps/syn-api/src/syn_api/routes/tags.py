"""Edit an execution's or a workflow's tags after creation (#967).

``POST .../tags`` adds the body's tags; ``DELETE .../tags?tag=`` removes the
named ones. Both are idempotent and neither replaces the set: adding a tag
already present, or removing one that is absent, succeeds and records nothing.
The removal names its tags in the query, spelled exactly like the ``?tag=``
list filter, because a DELETE body has no defined meaning in HTTP.

Every response is the aggregate's tag set after the edit, never the read
model's: the projection lags the event store, and a caller who just made an
edit must see that edit in the answer to it.

The domain decides everything here. ``TagSet`` rejects an invalid tag (422)
before a command exists; the aggregate refuses an empty edit or one past the
per-record limit (also 422); an id the event store does not know is 404.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from syn_adapters.projection_stores.prefix_match import format_ambiguous_error, resolve_by_prefix
from syn_api._wiring import (
    ensure_connected,
    get_projection_mgr,
    get_publisher,
    get_workflow_execution_repository,
    get_workflow_repo,
    sync_published_events_to_projections,
)
from syn_api.types import AddTagsRequest, ExecutionTagsResponse, WorkflowTagsResponse
from syn_domain.contexts.orchestration import (
    AddExecutionTagsCommand,
    AddExecutionTagsHandler,
    AddWorkflowTagsCommand,
    AddWorkflowTagsHandler,
    InvalidTagsError,
    RemoveExecutionTagsCommand,
    RemoveExecutionTagsHandler,
    RemoveWorkflowTagsCommand,
    RemoveWorkflowTagsHandler,
    TagSet,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import TagEditResult
    from syn_domain.contexts.orchestration.domain.aggregate_execution.execution_tags import (
        ExecutionTags,
    )

router = APIRouter(tags=["tags"])

_EDIT_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {"description": "No execution or workflow has this id"},
    409: {"description": "The id prefix matches more than one record"},
    422: {"description": "A tag is invalid, none was given, or the limit would be exceeded"},
}

_REMOVE_QUERY = Query(
    ...,
    description=(
        "A tag to remove. Repeat to remove several. Normalised like stored tags; "
        "an invalid tag is rejected with 422."
    ),
)


async def _resolve(namespace: str, raw_id: str, entity: str) -> str:
    """Expand a CLI id prefix to the full id, without letting the read model decide existence.

    The projection lags the event store, so a record created a moment ago may
    not be in it yet. A miss therefore falls through to the id as typed, and
    the aggregate answers whether it exists.
    """
    await ensure_connected()
    match = await resolve_by_prefix(get_projection_mgr().store, namespace, raw_id)
    if match.is_ambiguous:
        raise HTTPException(
            status_code=409, detail=format_ambiguous_error(entity, raw_id, match.candidates)
        )
    return match.full_id or raw_id


async def _settled[T](result: TagEditResult[T] | None, entity: str, entity_id: str) -> T:
    """The tags an edit left, or the HTTP error naming why there are none."""
    if result is None:
        raise HTTPException(status_code=404, detail=f"{entity} not found: {entity_id}")
    if not result.success or result.tags is None:
        raise HTTPException(status_code=422, detail=result.error)
    await sync_published_events_to_projections()
    return result.tags


def _removal(tag: list[str]) -> TagSet:
    try:
        return TagSet(tag)
    except InvalidTagsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _execution_response(execution_id: str, tags: ExecutionTags) -> ExecutionTagsResponse:
    return ExecutionTagsResponse(
        execution_id=execution_id,
        tags=list(tags.current),
        inherited_tags=list(tags.inherited),
    )


# =============================================================================
# Executions
# =============================================================================


@router.post(
    "/executions/{execution_id}/tags",
    response_model=ExecutionTagsResponse,
    responses=_EDIT_RESPONSES,
)
async def add_execution_tags_endpoint(
    execution_id: str, body: AddTagsRequest
) -> ExecutionTagsResponse:
    """Add tags to an execution, retroactively. Its inherited tags are never changed."""
    execution_id = await _resolve("workflow_execution_details", execution_id, "Execution")
    handler = AddExecutionTagsHandler(get_workflow_execution_repository(), get_publisher())
    result = await handler.handle(
        AddExecutionTagsCommand(aggregate_id=execution_id, tags=body.tags)
    )
    tags = await _settled(result, "Execution", execution_id)
    return _execution_response(execution_id, tags)


@router.delete(
    "/executions/{execution_id}/tags",
    response_model=ExecutionTagsResponse,
    responses=_EDIT_RESPONSES,
)
async def remove_execution_tags_endpoint(
    execution_id: str, tag: list[str] = _REMOVE_QUERY
) -> ExecutionTagsResponse:
    """Remove tags from an execution. Removing an inherited tag leaves `inherited_tags` alone."""
    tags_to_remove = _removal(tag)
    execution_id = await _resolve("workflow_execution_details", execution_id, "Execution")
    handler = RemoveExecutionTagsHandler(get_workflow_execution_repository(), get_publisher())
    result = await handler.handle(
        RemoveExecutionTagsCommand(aggregate_id=execution_id, tags=tags_to_remove)
    )
    tags = await _settled(result, "Execution", execution_id)
    return _execution_response(execution_id, tags)


# =============================================================================
# Workflows
# =============================================================================


@router.post(
    "/workflows/{workflow_id}/tags",
    response_model=WorkflowTagsResponse,
    responses=_EDIT_RESPONSES,
)
async def add_workflow_tags_endpoint(
    workflow_id: str, body: AddTagsRequest
) -> WorkflowTagsResponse:
    """Add tags to a workflow. Future runs inherit them; existing runs keep their own."""
    workflow_id = await _resolve("workflow_details", workflow_id, "Workflow")
    handler = AddWorkflowTagsHandler(get_workflow_repo(), get_publisher())
    result = await handler.handle(AddWorkflowTagsCommand(aggregate_id=workflow_id, tags=body.tags))
    tags = await _settled(result, "Workflow", workflow_id)
    return WorkflowTagsResponse(workflow_id=workflow_id, tags=list(tags))


@router.delete(
    "/workflows/{workflow_id}/tags",
    response_model=WorkflowTagsResponse,
    responses=_EDIT_RESPONSES,
)
async def remove_workflow_tags_endpoint(
    workflow_id: str, tag: list[str] = _REMOVE_QUERY
) -> WorkflowTagsResponse:
    """Remove tags from a workflow. Existing runs keep the tags they launched with."""
    tags_to_remove = _removal(tag)
    workflow_id = await _resolve("workflow_details", workflow_id, "Workflow")
    handler = RemoveWorkflowTagsHandler(get_workflow_repo(), get_publisher())
    result = await handler.handle(
        RemoveWorkflowTagsCommand(aggregate_id=workflow_id, tags=tags_to_remove)
    )
    tags = await _settled(result, "Workflow", workflow_id)
    return WorkflowTagsResponse(workflow_id=workflow_id, tags=list(tags))
