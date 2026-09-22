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
from syn_api.types import (
    Err,
    LocalTranscriptResponse,
    SessionInventoryJobResponse,
    SessionInventoryPageResponse,
    SessionInventoryRefreshRequest,
    SessionInventoryRefreshResponse,
    SessionInventoryResponse,
)
from syn_domain.contexts.agent_sessions import (
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
    )


@router.get("/executions/{execution_id}/session-inventory/{snapshot_id}/{kind}")
async def get_session_inventory_page(
    execution_id: str,
    snapshot_id: UUID,
    kind: ItemKind,
    after: Annotated[int, Query(ge=-1)] = -1,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SessionInventoryPageResponse:
    run = await _visible_run(execution_id)
    try:
        page = await get_inventory_runtime().inventory.page(
            run, snapshot_id, kind, after=after, limit=limit
        )
    except InventoryNotFound as exc:
        raise HTTPException(status_code=404, detail="Published inventory not found") from exc
    return SessionInventoryPageResponse.model_validate(page.model_dump())


@router.post("/executions/{execution_id}/session-inventory/reconcile", status_code=202)
async def refresh_session_inventory(
    execution_id: str,
    request: SessionInventoryRefreshRequest,
) -> SessionInventoryRefreshResponse:
    run = await _visible_run(execution_id)
    runtime = get_inventory_runtime()
    handler = RefreshSessionInventoryHandler(
        runtime.repository, runtime.evidence, runtime.inventory
    )
    try:
        job_id = await handler.handle(run, request.idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionInventoryRefreshResponse(job_id=job_id)


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
