"""Artifact API endpoints and service operations.

Provides listing, retrieving, creating, and uploading artifacts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import (
    ensure_connected,
    get_artifact_repo,
    get_projection_mgr,
    sync_published_events_to_projections,
)
from syn_api.list_query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    WindowBound,
    resolve_page_size,
)
from syn_api.types import (
    ArtifactActionResponse,
    ArtifactDetail,
    ArtifactError,
    ArtifactSummary,
    Err,
    Ok,
    Result,
)
from syn_domain.pagination import Page

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


# =============================================================================
# Response Models
# =============================================================================


class ArtifactSummaryResponse(BaseModel):
    """Summary of an artifact."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    artifact_type: str
    title: str | None = None
    size_bytes: int = 0
    created_at: str | None = None


class ArtifactListResponse(BaseModel):
    """One page of artifacts, and the numbers describing what it is a page of.

    The same envelope ``/executions`` and ``/sessions`` answer with, for the
    same reason: this endpoint used to return a bare array, so a response of 50
    rows was indistinguishable from a collection of 50 and a client had no
    number to page against (#1204). ``limit`` was the only parameter it
    honoured and it capped at 200, which made 200 artifacts the whole of
    reachable history.
    """

    artifacts: list[ArtifactSummaryResponse] = Field(default_factory=list)
    total: int = 0
    """Artifacts matching every filter, not the length of this page.

    Invariant under ``page_size``: it is the size of the collection the page
    was cut from. A total that moves when the page does is a page length
    wearing a count's name, which is what #1159 and #1160 were.
    """
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    type_counts: dict[str, int] = Field(default_factory=dict)
    """Matching artifacts tallied by type, ignoring the type filter itself.

    Named after its own dimension because artifacts have no status; it is the
    same facet the siblings report as ``status_counts``, counted over every
    OTHER filter the request carried so an option says what selecting it would
    return rather than how much of it landed on this page.
    """


class ArtifactResponse(BaseModel):
    """Detailed artifact response."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    session_id: str | None
    artifact_type: str
    is_primary_deliverable: bool = True
    content: str | None = None
    content_type: str = "text/markdown"
    content_hash: str | None = None
    size_bytes: int = 0
    title: str | None = None
    derived_from: list[str] = Field(default_factory=list)
    created_at: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def list_artifacts(
    workflow_id: str | None = None,
    session_id: str | None = None,
    phase_id: str | None = None,
    artifact_type: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    search: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> Result[Page[ArtifactSummary], ArtifactError]:
    """List artifacts, optionally filtered, as one page of a known collection.

    Returns a ``Page`` rather than a bare list because the endpoint needs the
    total and the type facets counted over the same predicate that produced the
    rows. Deriving them separately is how a count comes to describe rows the
    query does not return (#1119); returning neither is how this endpoint came
    to be unpageable at all (#1204).

    Every filter is applied where ``total`` is computed. They used to be split:
    the store applied ``workflow_id`` under a ``limit``, then ``phase_id`` and
    ``artifact_type`` were applied in Python to whatever rows survived it, so
    ``?artifact_type=plan`` answered "none" whenever the newest page happened
    to hold no plans -- a filter that searched a page, not the collection.

    Args:
        workflow_id: Filter by workflow ID.
        session_id: Filter by session ID.
        phase_id: Filter by phase ID.
        artifact_type: Filter by artifact type. Also the facet dimension, so
            the type counts still describe the other types.
        created_after: Inclusive lower bound on ``created_at``.
        created_before: Inclusive upper bound on ``created_at``.
        search: Case-insensitive substring match on artifact id, title,
            workflow id and phase id.
        limit: Rows on this page.
        offset: Rows to skip before this page.

    Returns:
        Ok(Page[ArtifactSummary]) on success, Err(ArtifactError) on failure.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.artifact_list
        domain_page = await projection.page(
            workflow_id=workflow_id,
            session_id=session_id,
            phase_id=phase_id,
            artifact_types=[artifact_type] if artifact_type else None,
            created_after=created_after,
            created_before=created_before,
            search=search,
            limit=limit,
            offset=offset,
        )
        return Ok(
            Page(
                rows=[
                    ArtifactSummary(
                        id=a.id,
                        workflow_id=a.workflow_id,
                        phase_id=a.phase_id,
                        artifact_type=a.artifact_type,
                        title=a.name,
                        size_bytes=a.size_bytes,
                        created_at=datetime.fromisoformat(a.created_at)
                        if isinstance(a.created_at, str)
                        else a.created_at,
                    )
                    for a in domain_page.rows
                ],
                total=domain_page.total,
                status_counts=domain_page.status_counts,
            )
        )
    except Exception as e:
        return Err(ArtifactError.STORAGE_ERROR, message=str(e))


async def _load_artifact_content(
    artifact_id: str, fallback_content: str | None
) -> tuple[str | None, str | None]:
    """Download artifact content from storage, falling back to projection content.

    Returns:
        (content, content_type) tuple.
    """
    try:
        from syn_adapters.storage.artifact_storage import get_artifact_storage

        storage = await get_artifact_storage()
        raw = await storage.download(artifact_id)
        return raw.decode("utf-8", errors="replace"), "text/plain"
    except Exception:
        logger.exception("Failed to load artifact content for %s", artifact_id)

    # Fall back to projection content if storage download failed
    if fallback_content is not None:
        return fallback_content, "text/plain"
    return None, None


def _parse_artifact_created_at(created_at: str | datetime | None) -> datetime | None:
    """Parse created_at from string or datetime."""
    if isinstance(created_at, str):
        return datetime.fromisoformat(created_at)
    return created_at


async def get_artifact(
    artifact_id: str,
    include_content: bool = False,
) -> Result[ArtifactDetail, ArtifactError]:
    """Get detailed artifact information, optionally with content.

    Args:
        artifact_id: The artifact ID.
        include_content: Whether to include the artifact content.

    Returns:
        Ok(ArtifactDetail) on success, Err(ArtifactError) on failure.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.artifact_list

        # Look up from projection. This read every artifact ever written and
        # scanned for the id, under a limit of 10000 -- so past that row the
        # only remaining way to reach an old artifact stopped working too
        # (#1204). The store is keyed by id.
        artifact = await projection.get_by_id(artifact_id)

        if artifact is None:
            return Err(ArtifactError.NOT_FOUND, message=f"Artifact {artifact_id} not found")

        content = None
        content_type = None
        if include_content:
            content, content_type = await _load_artifact_content(artifact_id, artifact.content)

        return Ok(
            ArtifactDetail(
                id=artifact.id,
                workflow_id=artifact.workflow_id,
                phase_id=artifact.phase_id,
                session_id=artifact.session_id,
                artifact_type=artifact.artifact_type,
                title=artifact.name,
                content=content,
                content_type=content_type,
                content_hash=artifact.content_hash,
                size_bytes=artifact.size_bytes,
                created_at=_parse_artifact_created_at(artifact.created_at),
            )
        )
    except Exception as e:
        if "not found" in str(e).lower():
            return Err(ArtifactError.NOT_FOUND, message=str(e))
        return Err(ArtifactError.STORAGE_ERROR, message=str(e))


async def create_artifact(
    workflow_id: str,
    artifact_type: str,
    title: str,
    content: str,
    phase_id: str | None = None,
    session_id: str | None = None,  # noqa: ARG001
    content_type: str = "text/markdown",  # noqa: ARG001
) -> Result[str, ArtifactError]:
    """Create a new artifact.

    Args:
        workflow_id: The workflow this artifact belongs to.
        artifact_type: Type of artifact (e.g., "code", "document", "report").
        title: Human-readable title.
        content: Artifact content.
        phase_id: Optional phase within the workflow.
        session_id: Optional session that created this artifact.
        content_type: MIME type of the content.

    Returns:
        Ok(artifact_id) on success, Err(ArtifactError) on failure.
    """
    from uuid import uuid4

    await ensure_connected()
    try:
        from syn_domain.contexts.artifacts import (
            ArtifactAggregate,
            ArtifactType,
            CreateArtifactCommand,
        )

        try:
            art_type = ArtifactType(artifact_type.lower())
        except ValueError:
            return Err(
                ArtifactError.INVALID_INPUT,
                message=f"Unknown artifact_type: '{artifact_type}'. "
                f"Valid types: {[t.value for t in ArtifactType]}",
            )

        artifact_id = str(uuid4())
        command = CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id=workflow_id,
            phase_id=phase_id or "",
            artifact_type=art_type,
            content=content,
            title=title,
        )

        repo = get_artifact_repo()
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(command)
        await repo.save(aggregate)
        await sync_published_events_to_projections()

        return Ok(artifact_id)
    except Exception as e:
        return Err(ArtifactError.STORAGE_ERROR, message=str(e))


async def upload_artifact(
    artifact_id: str,
    data: bytes,
    filename: str,  # noqa: ARG001
    content_type: str = "application/octet-stream",
) -> Result[str, ArtifactError]:
    """Upload binary content for an existing artifact.

    Args:
        artifact_id: The artifact to upload content for.
        data: Binary content to upload.
        filename: Original filename.
        content_type: MIME type of the uploaded content.

    Returns:
        Ok(storage_url) on success, Err(ArtifactError) on failure.
    """
    await ensure_connected()
    try:
        from syn_adapters.storage.artifact_storage import get_artifact_storage

        storage = await get_artifact_storage()
        result = await storage.upload(
            artifact_id=artifact_id,
            content=data,
            content_type=content_type,
        )
        return Ok(result.storage_uri if hasattr(result, "storage_uri") else str(result))
    except Exception as e:
        return Err(ArtifactError.STORAGE_ERROR, message=str(e))


# =============================================================================
# Request Models
# =============================================================================


async def update_artifact(
    artifact_id: str,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    is_primary_deliverable: bool | None = None,
) -> Result[None, ArtifactError]:
    """Update mutable metadata of an artifact."""
    await ensure_connected()
    try:
        from syn_domain.contexts.artifacts import ManageArtifactHandler, UpdateArtifactCommand

        command = UpdateArtifactCommand(
            aggregate_id=artifact_id,
            title=title,
            metadata=metadata,
            is_primary_deliverable=is_primary_deliverable,
        )

        repo = get_artifact_repo()
        handler = ManageArtifactHandler(repository=repo)
        await handler.update(command)
        await sync_published_events_to_projections()
        return Ok(None)
    except KeyError:
        return Err(ArtifactError.NOT_FOUND, message=f"Artifact {artifact_id} not found")
    except ValueError as e:
        if "deleted" in str(e).lower():
            return Err(ArtifactError.ALREADY_DELETED, message=str(e))
        return Err(ArtifactError.INVALID_INPUT, message=str(e))
    except Exception as e:
        return Err(ArtifactError.STORAGE_ERROR, message=str(e))


async def delete_artifact(
    artifact_id: str,
    deleted_by: str = "",
) -> Result[None, ArtifactError]:
    """Soft-delete an artifact."""
    await ensure_connected()
    try:
        from syn_domain.contexts.artifacts import DeleteArtifactCommand, ManageArtifactHandler

        command = DeleteArtifactCommand(
            aggregate_id=artifact_id,
            deleted_by=deleted_by,
        )

        repo = get_artifact_repo()
        handler = ManageArtifactHandler(repository=repo)
        await handler.delete(command)
        await sync_published_events_to_projections()
        return Ok(None)
    except KeyError:
        return Err(ArtifactError.NOT_FOUND, message=f"Artifact {artifact_id} not found")
    except ValueError as e:
        if "already deleted" in str(e).lower():
            return Err(ArtifactError.ALREADY_DELETED, message=str(e))
        return Err(ArtifactError.INVALID_INPUT, message=str(e))
    except Exception as e:
        return Err(ArtifactError.STORAGE_ERROR, message=str(e))


# =============================================================================
# Request Models
# =============================================================================


class UpdateArtifactRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str | None = None
    metadata: dict[str, Any] | None = None
    is_primary_deliverable: bool | None = None


class CreateArtifactRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    workflow_id: str
    artifact_type: str
    title: str
    content: str
    phase_id: str | None = None
    session_id: str | None = None
    content_type: str = "text/markdown"


class CreateArtifactResponse(BaseModel):
    id: str
    title: str
    artifact_type: str
    status: str


class UploadArtifactResponse(BaseModel):
    artifact_id: str
    storage_url: str
    status: str


class ArtifactContentResponse(BaseModel):
    artifact_id: str
    content: str | None
    content_type: str
    size_bytes: int | None


# Maximum upload size: 50 MB
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


# =============================================================================
# HTTP Endpoints
# =============================================================================


def _to_artifact_summary_response(a: ArtifactSummary) -> ArtifactSummaryResponse:
    """Convert an ArtifactSummary to its API response model."""
    return ArtifactSummaryResponse(
        id=a.id,
        workflow_id=a.workflow_id,
        phase_id=a.phase_id,
        artifact_type=a.artifact_type,
        title=a.title,
        size_bytes=a.size_bytes or 0,
        created_at=str(a.created_at) if a.created_at else None,
    )


@router.get("", response_model=ArtifactListResponse)
async def list_artifacts_endpoint(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    phase_id: str | None = Query(None, description="Filter by phase ID"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    created_after: WindowBound | None = Query(
        None, description="Inclusive ISO 8601 lower bound on created_at (timezone required)"
    ),
    created_before: WindowBound | None = Query(
        None, description="Inclusive ISO 8601 upper bound on created_at (timezone required)"
    ),
    q: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match against artifact id, title, workflow id and phase id"
        ),
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int | None = Query(None, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    limit: int | None = Query(
        None,
        ge=1,
        le=MAX_PAGE_SIZE,
        deprecated=True,
        description="Deprecated alias for page_size. Ignored when page_size is given.",
    ),
) -> ArtifactListResponse:
    """List artifacts with optional filtering.

    The window is named after ``created_at`` because that is the timestamp an
    artifact has; the siblings bound ``started_at`` and spell it
    ``started_after``. The validation is the same one (#1186): a bound with no
    offset is refused rather than guessed at.
    """
    effective_page_size = resolve_page_size(page_size, limit)
    result = await list_artifacts(
        workflow_id=workflow_id,
        session_id=session_id,
        phase_id=phase_id,
        artifact_type=artifact_type,
        created_after=created_after,
        created_before=created_before,
        search=q,
        limit=effective_page_size,
        offset=(page - 1) * effective_page_size,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    artifact_page = result.value
    return ArtifactListResponse(
        artifacts=[_to_artifact_summary_response(a) for a in artifact_page.rows],
        # The filtered COLLECTION, not this page. There was no count at all
        # before, so truncation was undetectable from the response (#1204).
        total=artifact_page.total,
        page=page,
        page_size=effective_page_size,
        type_counts=artifact_page.status_counts,
    )


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact_endpoint(
    artifact_id: str,
    include_content: bool = Query(True, description="Include artifact content in response"),
) -> ArtifactResponse:
    """Get artifact details by ID (supports partial ID prefix matching)."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    artifact_id = await resolve_or_raise(mgr.store, "artifact_summaries", artifact_id, "Artifact")
    result = await get_artifact(artifact_id, include_content=include_content)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    a = result.value

    if include_content and not a.content:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact {artifact_id} content not found in projection.",
        )

    return ArtifactResponse(
        id=a.id,
        workflow_id=a.workflow_id,
        phase_id=a.phase_id,
        session_id=a.session_id,
        artifact_type=a.artifact_type,
        is_primary_deliverable=True,
        content=a.content,
        content_type=a.content_type or "text/markdown",
        size_bytes=a.size_bytes or 0,
        title=a.title,
        derived_from=[],
        created_at=str(a.created_at) if a.created_at else None,
        created_by=None,
        metadata={},
    )


@router.get("/{artifact_id}/content", response_model=ArtifactContentResponse)
async def get_artifact_content_endpoint(artifact_id: str) -> ArtifactContentResponse:
    """Get artifact content only (for large artifacts)."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    artifact_id = await resolve_or_raise(mgr.store, "artifact_summaries", artifact_id, "Artifact")
    result = await get_artifact(artifact_id, include_content=True)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    a = result.value

    # The metadata projection lists the artifact but object storage hasn't received
    # the bytes yet — a race between ArtifactCreatedEvent and the MinIO upload (#700).
    # Signal retry-later instead of a misleading 200-with-null body.
    if a.content is None and a.size_bytes and a.size_bytes > 0:
        raise HTTPException(
            status_code=202,
            detail=f"Artifact {artifact_id} content not yet available; retry shortly",
            headers={"Retry-After": "2"},
        )

    return ArtifactContentResponse(
        artifact_id=artifact_id,
        content=a.content,
        content_type=a.content_type or "text/markdown",
        size_bytes=a.size_bytes,
    )


@router.post("", response_model=CreateArtifactResponse, status_code=201)
async def create_artifact_endpoint(body: CreateArtifactRequest) -> CreateArtifactResponse:
    """Create a new artifact."""
    result = await create_artifact(
        workflow_id=body.workflow_id,
        artifact_type=body.artifact_type,
        title=body.title,
        content=body.content,
        phase_id=body.phase_id,
        session_id=body.session_id,
        content_type=body.content_type,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return CreateArtifactResponse(
        id=result.value,
        title=body.title,
        artifact_type=body.artifact_type,
        status="created",
    )


@router.put("/{artifact_id}", response_model=ArtifactActionResponse)
async def update_artifact_endpoint(
    artifact_id: str, body: UpdateArtifactRequest
) -> ArtifactActionResponse:
    """Update artifact metadata."""
    result = await update_artifact(
        artifact_id=artifact_id,
        title=body.title,
        metadata=body.metadata,
        is_primary_deliverable=body.is_primary_deliverable,
    )

    if isinstance(result, Err):
        if result.error == ArtifactError.NOT_FOUND:
            raise HTTPException(status_code=404, detail=result.message)
        if result.error == ArtifactError.ALREADY_DELETED:
            raise HTTPException(status_code=409, detail=result.message)
        if result.error == ArtifactError.STORAGE_ERROR:
            raise HTTPException(status_code=500, detail=result.message)
        raise HTTPException(status_code=400, detail=result.message)

    return ArtifactActionResponse(artifact_id=artifact_id, status="updated")


@router.delete("/{artifact_id}", response_model=ArtifactActionResponse)
async def delete_artifact_endpoint(artifact_id: str) -> ArtifactActionResponse:
    """Soft-delete an artifact."""
    result = await delete_artifact(artifact_id=artifact_id, deleted_by="api")

    if isinstance(result, Err):
        if result.error == ArtifactError.NOT_FOUND:
            raise HTTPException(status_code=404, detail=result.message)
        if result.error == ArtifactError.ALREADY_DELETED:
            raise HTTPException(status_code=409, detail=result.message)
        if result.error == ArtifactError.STORAGE_ERROR:
            raise HTTPException(status_code=500, detail=result.message)
        raise HTTPException(status_code=400, detail=result.message)

    return ArtifactActionResponse(artifact_id=artifact_id, status="deleted")


@router.post("/{artifact_id}/upload", response_model=UploadArtifactResponse)
async def upload_artifact_endpoint(artifact_id: str, file: UploadFile) -> UploadArtifactResponse:
    """Upload binary content for an existing artifact (max 50 MB)."""
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds maximum size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    result = await upload_artifact(
        artifact_id=artifact_id,
        data=data,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return UploadArtifactResponse(
        artifact_id=artifact_id,
        storage_url=result.value,
        status="uploaded",
    )
