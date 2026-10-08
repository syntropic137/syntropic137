"""Evals: create, list, show, archive, their runs, and membership edits (#967).

``POST /evals`` mints the eval id on the server. A caller-chosen id could equal
another aggregate's id, and the event store keys a stream by aggregate id alone
(#1557), so the eval would share that aggregate's stream. Every write answers
with a receipt read from the Eval aggregate; the list and detail routes read the
eval projection, which may not show a just-created eval for a moment.

``GET /evals/{id}/runs`` serves the same member rows ``GET /executions?eval_id=``
returns, each as one data point: the models its phases actually ran, its cost,
and its current score (``eval_runs``). ``POST /evals/{id}/runs/{exec}/score``
records a score; only a current member can be scored.

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

from typing import TYPE_CHECKING, Literal

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
from syn_api._wiring_evals import get_revision_resolver
from syn_api.list_query import MAX_PAGE_SIZE
from syn_api.routes.eval_runs import (
    eval_run_page,
    eval_summary,
    pass_rate_display,
    stats_response,
    variant_responses,
)
from syn_api.services.read_model_status import read_model_status
from syn_api.types import (
    AttachEvalRequest,
    CreateEvalRequest,
    EvalArchivedResponse,
    EvalBaselineRepoResponse,
    EvalCreatedResponse,
    EvalDetailResponse,
    EvalListResponse,
    EvalResponse,
    EvalRunListResponse,
    EvalRunScoreRequest,
    EvalRunScoreResponse,
    ExecutionEvalResponse,
    SetDefaultEvalRequest,
    WorkflowDefaultEvalResponse,
)
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import (
    ArchiveEvalHandler,
    AttachExecutionToEvalCommand,
    AttachExecutionToEvalHandler,
    BaselineRequest,
    CreateEvalHandler,
    DetachExecutionFromEvalCommand,
    DetachExecutionFromEvalHandler,
    EvalId,
    EvalRunNotMemberError,
    EvalUnavailableError,
    Goal,
    RecordEvalRunScoreCommand,
    RecordEvalRunScoreHandler,
    SetWorkflowDefaultEvalCommand,
    SetWorkflowDefaultEvalHandler,
)
from syn_domain.contexts.orchestration.slices.list_evals.projection import EvalListProjection

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.orchestration import EvalMembershipResult
    from syn_domain.contexts.orchestration.domain.read_models.eval_summary import EvalRecord

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


_EVAL_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {
        "description": "No eval has this id in the eval read model (it may still be catching up)"
    },
    422: {"description": "The eval id is not a valid eval id"},
}


async def _response(
    manager: ProjectionManager, record: EvalRecord, run_count: int, tally: dict[str, int]
) -> EvalResponse:
    summary = await eval_summary(manager, record.eval_id)
    return EvalResponse(
        eval_id=record.eval_id,
        name=record.name,
        goal=record.goal,
        starting_workflow_id=record.starting_workflow_id,
        baseline_repos=[
            EvalBaselineRepoResponse(
                repository=f"{repo.owner}/{repo.name}",
                requested_ref=repo.requested_ref,
                commit_sha=repo.commit_sha,
            )
            for repo in record.baseline_repos
        ],
        tags=list(record.tags),
        frozen=record.frozen,
        archived=record.archived,
        created_at=record.created_at,
        updated_at=record.updated_at,
        run_count=run_count,
        run_status_counts=tally,
        scored_count=summary.scored_count,
        pass_rate=summary.pass_rate,
        pass_rate_display=pass_rate_display(summary.pass_rate),
        last_run_at=summary.last_run_at,
        last_verdict=summary.last_verdict,
        variants=variant_responses(summary),
        stats=stats_response(summary.stats),
    )


def _baseline_requests(body: CreateEvalRequest) -> list[BaselineRequest]:
    try:
        return [
            BaselineRequest(
                repository=RepositoryRef.from_slug(repo.repository),
                requested_ref=repo.requested_ref,
            )
            for repo in body.baseline_repos
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evals",
    response_model=EvalCreatedResponse,
    status_code=201,
    responses={
        422: {"description": "The request is invalid, or a baseline ref could not be resolved"},
    },
)
async def create_eval_endpoint(body: CreateEvalRequest) -> EvalCreatedResponse:
    """Create an eval, pinning each baseline ref to a commit SHA. The id is minted here."""
    baseline = _baseline_requests(body)
    try:
        goal = Goal(body.goal)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
    await ensure_connected()
    eval_id = EvalId.new()
    repository = get_eval_repo()
    handler = CreateEvalHandler(repository, get_revision_resolver(), get_publisher())
    result = await handler.handle(
        eval_id=eval_id,
        name=body.name,
        goal=goal,
        baseline=baseline,
        tags=body.tags,
        starting_workflow_id=body.starting_workflow_id,
    )
    if not result.success:
        raise HTTPException(status_code=422, detail=result.error)
    await sync_published_events_to_projections()
    # The receipt is the aggregate as the store holds it, not the eval projection,
    # which may not have applied EvalCreated yet.
    created = await repository.get_by_id(str(eval_id))
    if created is None or created.name is None or created.goal is None:
        msg = f"eval {eval_id} was saved but cannot be loaded"
        raise RuntimeError(msg)
    return EvalCreatedResponse(
        eval_id=str(eval_id),
        name=created.name,
        goal=str(created.goal),
        starting_workflow_id=created.starting_workflow_id,
        baseline_repos=[
            EvalBaselineRepoResponse(
                repository=repo.repository.slug,
                requested_ref=repo.requested_ref,
                commit_sha=repo.commit_sha,
            )
            for repo in created.baseline_repos
        ],
        tags=list(created.tags),
    )


@router.get("/evals", response_model=EvalListResponse)
async def list_evals_endpoint(
    status: Literal["active", "archived"] | None = Query(
        None, description="Keep only active or only archived evals. Both when omitted."
    ),
    q: str | None = Query(None, description="Case-insensitive match on id, name and goal"),
    tag: list[str] | None = Query(None, description="Keep evals carrying this tag; repeat for AND"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> EvalListResponse:
    """List evals, newest first, each with its run count and status tally."""
    await ensure_connected()
    manager = get_projection_mgr()
    result = await manager.eval_list.page(
        statuses=[status] if status else None,
        search=q,
        tags=tag,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return EvalListResponse(
        evals=[
            await _response(manager, row.record, row.run_count, row.run_status_counts)
            for row in result.rows
        ],
        total=result.total,
        page=page,
        page_size=page_size,
        status_counts=result.status_counts,
        read_model_status=await read_model_status(EvalListProjection.PROJECTION_NAME),
    )


@router.get("/evals/{eval_id}", response_model=EvalDetailResponse, responses=_EVAL_RESPONSES)
async def get_eval_endpoint(eval_id: str) -> EvalDetailResponse:
    """One eval with its Baseline and run tally. Its runs are `GET /evals/{eval_id}/runs`."""
    from syn_api.prefix_resolver import resolve_or_raise

    await ensure_connected()
    eval_id = await resolve_or_raise(get_projection_mgr().store, "evals", eval_id, "Eval")
    manager = get_projection_mgr()
    detail = await manager.eval_list.detail(eval_id, limit=0)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Eval not found: {eval_id}")
    row = await _response(manager, detail.record, detail.runs.total, detail.runs.status_counts)
    return EvalDetailResponse(
        **row.model_dump(),
        read_model_status=await read_model_status(EvalListProjection.PROJECTION_NAME),
    )


@router.get("/evals/{eval_id}/runs", response_model=EvalRunListResponse, responses=_EVAL_RESPONSES)
async def list_eval_runs_endpoint(
    eval_id: str,
    statuses: str | None = Query(None, description="Comma-separated execution statuses (OR'd)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> EvalRunListResponse:
    """The executions currently in an eval, newest first, each with what it ran and its score.

    The eval id may be a unique prefix, as on `GET /evals/{eval_id}`; an id
    matching no eval is a 404. An eval with no runs is an empty page.
    """
    from syn_api.prefix_resolver import resolve_or_raise

    await ensure_connected()
    manager = get_projection_mgr()
    eval_id = await resolve_or_raise(manager.store, "evals", eval_id, "Eval")
    wanted = [s.strip() for s in statuses.split(",") if s.strip()] if statuses else None
    return await eval_run_page(manager, eval_id, page=page, page_size=page_size, statuses=wanted)


@router.post(
    "/evals/{eval_id}/runs/{execution_id}/score",
    response_model=EvalRunScoreResponse,
    responses={
        404: {"description": "No eval has this id"},
        409: {"description": "The execution is not currently a run of this eval"},
        422: _EVAL_RESPONSES[422],
    },
)
async def score_eval_run_endpoint(
    eval_id: str, execution_id: str, body: EvalRunScoreRequest
) -> EvalRunScoreResponse:
    """Record a verdict on one run. Re-scoring replaces the run's current score.

    Allowed on frozen and archived evals: judging a run is not editing the eval.
    """
    command = RecordEvalRunScoreCommand(
        eval_id=_eval_id(eval_id),
        execution_id=execution_id,
        verdict=body.verdict,
        score=body.score,
        evidence=body.evidence,
        scorer=body.scorer,
        scorer_version=body.scorer_version,
    )
    await ensure_connected()
    repository = get_eval_repo()
    handler = RecordEvalRunScoreHandler(
        repository, get_workflow_execution_repository(), get_publisher()
    )
    try:
        result = await handler.handle(command)
    except EvalRunNotMemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Eval not found: {command.eval_id}")
    if not result.success:
        raise HTTPException(status_code=409, detail=result.error)
    await sync_published_events_to_projections()
    # The receipt is the aggregate as the store holds it: the eval read model
    # may not have applied EvalRunScored yet.
    stored = await repository.get_by_id(command.aggregate_id)
    recorded = None if stored is None else stored.run_score(execution_id)
    if recorded is None:
        msg = f"score for {execution_id} on eval {command.eval_id} was saved but cannot be loaded"
        raise RuntimeError(msg)
    return EvalRunScoreResponse(
        eval_id=command.aggregate_id,
        execution_id=execution_id,
        verdict=recorded.verdict,
        score=recorded.score,
        evidence=recorded.evidence,
        scorer=recorded.scorer,
        scorer_version=recorded.scorer_version,
        scored_at=recorded.scored_at.isoformat(),
    )


@router.post(
    "/evals/{eval_id}/archive",
    response_model=EvalArchivedResponse,
    responses={404: {"description": "No eval has this id"}, 422: _EVAL_RESPONSES[422]},
)
async def archive_eval_endpoint(eval_id: str) -> EvalArchivedResponse:
    """Archive an eval: it stays readable with its runs, and admits no new ones. Idempotent."""
    archive = _eval_id(eval_id)
    await ensure_connected()
    result = await ArchiveEvalHandler(get_eval_repo(), get_publisher()).handle(eval_id=archive)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Eval not found: {archive}")
    if not result.success:
        raise HTTPException(status_code=409, detail=result.error)
    await sync_published_events_to_projections()
    return EvalArchivedResponse(eval_id=str(archive), archived=True)
