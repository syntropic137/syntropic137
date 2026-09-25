"""Local transcript bodies: read, revoke, delete and retract (#1398 rows 10/11).

Authorization is the ADR-059 installation boundary: the gateway authenticates
the caller, ``_visible_run`` checks the execution is visible now, and the exact
revision must be catalogued for that run. Revocation and deletion are keyed by
the archived bytes, so they apply to every run whose membership shares the
object (whole-object authorization); a frozen inventory revision never grants
access. Identifiers are opaque lookup keys, never paths or fetch URLs. Error
bodies are fixed strings: exception text can carry paths, tokens or payloads.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response

from syn_api._wiring_inventory import get_inventory_runtime
from syn_api.routes.executions.inventory import _visible_run
from syn_api.types import (
    LocalTranscriptResponse,
    TranscriptDeletionRequest,
    TranscriptDeletionResponse,
    TranscriptIdentityRequest,
    TranscriptRevocationResponse,
)
from syn_domain.contexts.agent_sessions import (
    QualifiedSessionIdentity,
    TranscriptIntegrityError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import (
        CataloguedCapture,
        RunIdentity,
    )

router = APIRouter(tags=["executions"])

_NO_STORE = {"Cache-Control": "no-store"}
_ArchiveHash = Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]
_OpaqueQuery = Annotated[str, Query(min_length=1, max_length=2048, pattern=r"^[^\x00]+$")]


def _denied(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail, headers=_NO_STORE)


def _identity(run: RunIdentity, harness: str, native_id: str) -> QualifiedSessionIdentity:
    try:
        return QualifiedSessionIdentity(
            kind="transcript",
            source_instance_id=run.source_instance_id,
            harness=harness,
            local_id=native_id,
        )
    except ValueError as exc:
        raise _denied(422, "Invalid transcript identity") from exc


async def _catalogued(
    execution_id: str, archive_hash: str, identity: TranscriptIdentityRequest
) -> CataloguedCapture:
    """The exact revision must belong to this visible run; otherwise 404, no metadata."""
    run = await _visible_run(execution_id)
    qualified = _identity(run, identity.harness, identity.native_id)
    try:
        capture = await get_inventory_runtime().catalog.get_revision(run, qualified, archive_hash)
    except OSError as exc:
        raise _denied(503, "Transcript storage unavailable") from exc
    if capture is None:
        raise _denied(404, "Transcript revision not found")
    return capture


@router.get("/executions/{execution_id}/session-transcripts/{archive_hash}")
async def get_local_transcript_revision(
    execution_id: str,
    archive_hash: _ArchiveHash,
    harness: _OpaqueQuery,
    native_id: _OpaqueQuery,
    response: Response,
) -> LocalTranscriptResponse:
    """Serve one exact archived revision after current whole-object authorization.

    Bytes are returned exactly as archived (source redaction only). Deleted,
    expired, missing and oversized bodies are explicit statuses, never content.
    """
    response.headers["Cache-Control"] = "no-store"
    run = await _visible_run(execution_id)
    identity = _identity(run, harness, native_id)
    try:
        result = await get_inventory_runtime().transcripts.handle(run, identity, archive_hash)
    except PermissionError as exc:
        raise _denied(403, "Transcript access denied") from exc
    except (OSError, TranscriptIntegrityError) as exc:
        raise _denied(503, "Transcript storage unavailable") from exc
    return LocalTranscriptResponse(
        status=result.status,
        archive_sha256=archive_hash,
        content_format=result.capture.content_format if result.capture is not None else None,
        size=result.capture.archive.size if result.capture is not None else None,
        content_base64=base64.b64encode(result.body).decode("ascii")
        if result.body is not None
        else None,
    )


@router.post(
    "/executions/{execution_id}/session-transcripts/{archive_hash}/deletion",
    status_code=202,
)
async def delete_local_transcript_revision(
    execution_id: str,
    archive_hash: _ArchiveHash,
    request: TranscriptDeletionRequest,
    response: Response,
) -> TranscriptDeletionResponse:
    """Durably tombstone exact bytes, then erase them asynchronously.

    Idempotent: repeating the request returns the existing tombstone. The body is
    withheld from the moment of the request for every run sharing the object.
    Deletion propagates to the configured replica; retries, replays and
    re-uploads cannot restore the bytes. Session history stays discoverable.
    """
    response.headers["Cache-Control"] = "no-store"
    capture = await _catalogued(execution_id, archive_hash, request)
    try:
        state, created = await get_inventory_runtime().deletions.request(capture, request.reason)
    except PermissionError as exc:
        raise _denied(403, "Transcript access denied") from exc
    except OSError as exc:
        raise _denied(503, "Transcript storage unavailable") from exc
    return TranscriptDeletionResponse(deletion=state, created=created)


@router.get("/executions/{execution_id}/session-transcripts/{archive_hash}/deletion")
async def get_local_transcript_deletion(
    execution_id: str,
    archive_hash: _ArchiveHash,
    harness: _OpaqueQuery,
    native_id: _OpaqueQuery,
    response: Response,
) -> TranscriptDeletionResponse:
    """Local erasure and replica propagation state of an existing tombstone."""
    response.headers["Cache-Control"] = "no-store"
    capture = await _catalogued(
        execution_id, archive_hash, TranscriptIdentityRequest(harness=harness, native_id=native_id)
    )
    try:
        state = await get_inventory_runtime().deletions.state(capture)
    except PermissionError as exc:
        raise _denied(403, "Transcript access denied") from exc
    except OSError as exc:
        raise _denied(503, "Transcript storage unavailable") from exc
    if state is None:
        raise _denied(404, "Transcript deletion not found")
    return TranscriptDeletionResponse(deletion=state, created=False)


@router.post("/executions/{execution_id}/session-transcripts/{archive_hash}/revocation")
async def revoke_local_transcript_revision(
    execution_id: str,
    archive_hash: _ArchiveHash,
    request: TranscriptIdentityRequest,
    response: Response,
) -> TranscriptRevocationResponse:
    """Withhold reads of exact bytes for every sharing run; bytes are retained."""
    response.headers["Cache-Control"] = "no-store"
    capture = await _catalogued(execution_id, archive_hash, request)
    try:
        created = await get_inventory_runtime().access.revoke(capture.archive)
    except OSError as exc:
        raise _denied(503, "Transcript storage unavailable") from exc
    return TranscriptRevocationResponse(archive_sha256=capture.archive.sha256, created=created)
