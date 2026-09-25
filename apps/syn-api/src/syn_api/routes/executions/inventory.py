"""Run inventory reads under the same gateway access boundary as executions.

Every page checks current execution visibility. A snapshot identifier is not an
access credential. Reads never launch capture, reconciliation, or remote I/O.
"""

from __future__ import annotations

import base64
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response

from syn_api._wiring_inventory import get_inventory_runtime
from syn_api.routes.executions.inventory_cursor import (
    MAX_CURSOR_LENGTH,
    InventoryCursor,
    InventoryCursorInvalid,
    issue_cursor,
)
from syn_api.routes.executions.inventory_summary import build_summary
from syn_api.types import (
    Err,
    LocalTranscriptResponse,
    SessionHistoryBackfillSummary,
    SessionInventoryBackfillRequest,
    SessionInventoryBackfillResponse,
    SessionInventoryCursorError,
    SessionInventoryCursorErrorResponse,
    SessionInventoryJobResponse,
    SessionInventoryNodeResponse,
    SessionInventoryPageResponse,
    SessionInventoryRefreshRequest,
    SessionInventoryRefreshResponse,
    SessionInventoryResponse,
)
from syn_domain.contexts.agent_sessions import (
    HistoricalAcquisitionQuotaExceeded,
    HistoryBackfillItem,
    InventoryFilter,
    InventoryJob,
    InventoryNotFound,
    InventorySnapshot,
    ItemKind,
    QualifiedSessionIdentity,
    RefreshSessionInventoryHandler,
    RunIdentity,
    TranscriptIntegrityError,
)

router = APIRouter(tags=["executions"])


async def _visible_run(execution_id: str) -> RunIdentity:
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise
    from syn_api.routes.executions.queries import get_detail

    manager = get_projection_mgr()
    resolved = await resolve_or_raise(
        manager.store, "workflow_execution_details", execution_id, "Execution"
    )
    if isinstance(await get_detail(resolved), Err):
        raise HTTPException(status_code=404, detail="Execution not found")
    return RunIdentity(
        source_instance_id=get_inventory_runtime().source_instance_id,
        execution_id=resolved,
    )


def _reconstruction_status(
    snapshot: InventorySnapshot | None,
    job: InventoryJob | None,
    later: bool,
) -> Literal["not_started", "pending", "running", "current", "failed"]:
    published = snapshot.evidence_watermark if snapshot is not None else 0
    status: Literal["not_started", "pending", "running", "current", "failed"] = "not_started"
    if snapshot is not None:
        status = "current"
    if later:
        status = "pending"
    # An older failed job cannot hide a more recent successful publication.
    if job is not None and (
        snapshot is None
        or job.state.request.evidence_watermark > published
        or job.state.request.expected_head == snapshot.snapshot_id
    ):
        status = "pending"
        if job.state.stage.value == "publishing":
            status = "running"
        elif job.state.stage.value == "failed":
            status = "failed"
    return status


@router.get("/executions/{execution_id}/session-inventory")
async def get_session_inventory(execution_id: str) -> SessionInventoryResponse:
    run = await _visible_run(execution_id)
    runtime = get_inventory_runtime()
    # Head first: a concurrently appended record may make this response pending,
    # but must never make an older snapshot appear caught up with newer evidence.
    snapshot = await runtime.inventory.head(run)
    job = await runtime.jobs.latest(run)
    watermark = await runtime.evidence.watermark(run)
    published = snapshot.evidence_watermark if snapshot is not None else 0
    later = watermark > published
    status = _reconstruction_status(snapshot, job, later)
    return SessionInventoryResponse(
        run=run,
        snapshot=snapshot,
        reconstruction_status=status,
        observed_evidence_watermark=watermark,
        later_evidence_pending=later,
        job_id=job.job_id if job is not None else None,
        summary=build_summary(
            execution_id=run.execution_id,
            snapshot=snapshot,
            status=status,
            later_evidence_pending=later,
            remote_replication="enabled" if runtime.replication is not None else "disabled",
        ),
    )


_FilterId = Annotated[
    str | None, Query(min_length=1, max_length=2048, pattern=r"^[^\x00]*\S[^\x00]*$")
]


def _cursor_error(status: int, error: SessionInventoryCursorError) -> HTTPException:
    return HTTPException(status_code=status, detail=error.model_dump(mode="json"))


def _resume_after(
    cursor: str | None,
    run: RunIdentity,
    snapshot_id: UUID,
    kind: ItemKind,
    filters: InventoryFilter,
) -> int:
    if cursor is None:
        return -1
    try:
        decoded = InventoryCursor.decode(cursor)
    except InventoryCursorInvalid as exc:
        raise _cursor_error(
            400,
            SessionInventoryCursorError(
                code="cursor_invalid", message="Inventory cursor is malformed", restart=True
            ),
        ) from exc
    mismatched = decoded.mismatches(run, snapshot_id, kind, filters)
    if mismatched:
        raise _cursor_error(
            400,
            SessionInventoryCursorError(
                code="cursor_mismatch",
                message="Inventory cursor belongs to another scope, revision, section or filter",
                mismatched=mismatched,
                restart=False,
            ),
        )
    return decoded.after


@router.get(
    "/executions/{execution_id}/session-inventory/{snapshot_id}/{kind}",
    responses={
        400: {"model": SessionInventoryCursorErrorResponse},
        410: {"model": SessionInventoryCursorErrorResponse},
    },
)
async def get_session_inventory_page(
    execution_id: str,
    snapshot_id: UUID,
    kind: ItemKind,
    phase_id: _FilterId = None,
    attempt_id: _FilterId = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=MAX_CURSOR_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SessionInventoryPageResponse:
    """Keyset page of one pinned revision, narrowed to a phase/attempt membership in SQL.

    Omit ``cursor`` for the first page, then pass ``next_cursor`` unchanged with
    the same revision, section and filters. A mismatched cursor is rejected; a
    cursor whose revision is no longer retained gets 410 with ``restart``.
    """
    run = await _visible_run(execution_id)
    filters = InventoryFilter(phase_id=phase_id, attempt_id=attempt_id)
    after = _resume_after(cursor, run, snapshot_id, kind, filters)
    runtime = get_inventory_runtime()
    try:
        page = await runtime.inventory.query(
            run, snapshot_id, kind, filters=filters, after=after, limit=limit
        )
    except InventoryNotFound as exc:
        if cursor is None:
            raise HTTPException(status_code=404, detail="Published inventory not found") from exc
        head = await runtime.inventory.head(run)
        raise _cursor_error(
            410,
            SessionInventoryCursorError(
                code="cursor_expired",
                message="Pinned inventory revision is no longer available; restart from the head",
                restart=True,
                restart_snapshot_id=str(head.snapshot_id) if head is not None else None,
            ),
        ) from exc
    overrides = await runtime.body_availability.overrides(page) if kind == "capture" else ()
    next_cursor = (
        issue_cursor(run, snapshot_id, kind, filters, page.last_ordinal)
        if page.has_more and page.last_ordinal is not None
        else None
    )
    return SessionInventoryPageResponse(
        snapshot=page.snapshot,
        kind=page.kind,
        filters=page.filters,
        items=page.items,
        item_keys=page.item_keys,
        next_cursor=next_cursor,
        body_overrides=overrides,
    )


@router.get("/executions/{execution_id}/session-inventory/{snapshot_id}/nodes/{node_key}")
async def get_session_inventory_node(
    execution_id: str,
    snapshot_id: UUID,
    node_key: Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")],
) -> SessionInventoryNodeResponse:
    """Resolve an edge endpoint on another page. Keys outside this revision stay opaque."""
    run = await _visible_run(execution_id)
    try:
        node = await get_inventory_runtime().inventory.node(run, snapshot_id, node_key)
    except InventoryNotFound as exc:
        raise HTTPException(status_code=404, detail="Published inventory not found") from exc
    return SessionInventoryNodeResponse(
        snapshot_id=str(snapshot_id),
        node_key=node_key,
        status="resolved" if node is not None else "unresolved",
        node=node,
    )


@router.post("/executions/{execution_id}/session-inventory/reconcile", status_code=202)
async def refresh_session_inventory(
    execution_id: str,
    request: SessionInventoryRefreshRequest,
) -> SessionInventoryRefreshResponse:
    run = await _visible_run(execution_id)
    runtime = get_inventory_runtime()
    if request.include_history:
        return await _backfill_history(run, request.idempotency_key)
    handler = RefreshSessionInventoryHandler(
        runtime.repository, runtime.evidence, runtime.inventory
    )
    try:
        job_id = await handler.handle(run, request.idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionInventoryRefreshResponse(job_id=job_id)


async def _backfill_history(run: RunIdentity, key: str) -> SessionInventoryRefreshResponse:
    """Local reads only. A retry with the same key resumes from durable receipts."""
    history = get_inventory_runtime().history
    if history is None:
        raise HTTPException(status_code=503, detail="Historical backfill is not configured")
    try:
        result = await history.handle(run, key)
    except HistoricalAcquisitionQuotaExceeded as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionInventoryRefreshResponse(
        job_id=result.job_id,
        history=SessionHistoryBackfillSummary(
            receipts=result.receipts,
            materialized=result.materialized,
            evidence_watermark=result.evidence_watermark,
        ),
    )


@router.post("/session-inventory/backfill", status_code=202)
async def backfill_all_session_inventories(
    request: SessionInventoryBackfillRequest,
) -> SessionInventoryBackfillResponse:
    """Queue every known execution. The live inventory worker drains the durable list."""
    from syn_api._wiring import get_projection_mgr

    runtime = get_inventory_runtime()
    if runtime.history is None:
        raise HTTPException(status_code=503, detail="Historical backfill is not configured")
    records = await get_projection_mgr().store.get_by_prefix("workflow_execution_details", "")
    items = tuple(
        HistoryBackfillItem(
            run=RunIdentity(source_instance_id=runtime.source_instance_id, execution_id=key),
            idempotency_key=request.idempotency_key,
        )
        for key in sorted({key for key, _ in records if key.strip()})
    )
    enqueued = 0
    for start in range(0, len(items), 500):
        enqueued += await runtime.history_queue.enqueue(items[start : start + 500])
    return SessionInventoryBackfillResponse(executions=len(items), enqueued=enqueued)


async def _resolve_inventory_job_id(job_id: str) -> str:
    # Full UUIDs must work before the asynchronous job projection catches up.
    try:
        return str(UUID(job_id))
    except ValueError:
        pass
    runtime = get_inventory_runtime()
    matches = await runtime.jobs.find_ids(runtime.source_instance_id, job_id)
    if len(matches) == 0:
        raise HTTPException(status_code=404, detail="Inventory job not found")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409, detail="Ambiguous inventory job ID; use a longer prefix"
        )
    (resolved,) = matches
    return resolved


@router.get("/session-inventory-jobs/{job_id}")
async def get_session_inventory_job(job_id: str) -> SessionInventoryJobResponse:
    runtime = get_inventory_runtime()
    job_id = await _resolve_inventory_job_id(job_id)
    aggregate = await runtime.repository.get_by_id(job_id)
    if aggregate is None or aggregate.state is None:
        raise HTTPException(status_code=404, detail="Inventory job not found")
    state = aggregate.state
    if state.request.run.source_instance_id != runtime.source_instance_id:
        raise HTTPException(status_code=404, detail="Inventory job not found")
    await _visible_run(state.request.run.execution_id)
    return SessionInventoryJobResponse(
        job_id=str(job_id),
        run=state.request.run,
        stage=state.stage.value,
        evidence_watermark=state.request.evidence_watermark,
        snapshot_id=str(state.request.snapshot_id),
        resolver_version=state.request.resolver_version,
        revision=state.revision,
        failure_code=state.failure_code,
    )


@router.get("/executions/{execution_id}/session-transcripts/{archive_hash}")
async def get_local_transcript_revision(
    execution_id: str,
    archive_hash: Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")],
    harness: Annotated[str, Query(min_length=1, max_length=2048, pattern=r"^[^\x00]+$")],
    native_id: Annotated[str, Query(min_length=1, max_length=2048, pattern=r"^[^\x00]+$")],
    response: Response,
) -> LocalTranscriptResponse:
    response.headers["Cache-Control"] = "no-store"
    run = await _visible_run(execution_id)
    try:
        identity = QualifiedSessionIdentity(
            kind="transcript",
            source_instance_id=run.source_instance_id,
            harness=harness,
            local_id=native_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid transcript identity") from exc
    try:
        result = await get_inventory_runtime().transcripts.handle(run, identity, archive_hash)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail="Transcript access denied",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except (OSError, TranscriptIntegrityError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Transcript storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    return LocalTranscriptResponse(
        status=result.status,
        archive_sha256=archive_hash,
        content_format=result.capture.content_format if result.capture is not None else None,
        size=result.capture.archive.size if result.capture is not None else None,
        content_base64=base64.b64encode(result.body).decode("ascii")
        if result.body is not None
        else None,
    )
