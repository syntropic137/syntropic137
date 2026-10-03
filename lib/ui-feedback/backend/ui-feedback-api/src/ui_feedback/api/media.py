"""Media upload/download API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ui_feedback.config import settings
from ui_feedback.models import MediaItem, MediaType
from ui_feedback.storage.protocol import FeedbackStorageProtocol

router = APIRouter(prefix="/feedback/{feedback_id}/media", tags=["media"])


def _valid_media(mime_type: str, data: bytes, media_type: MediaType) -> bool:
    """Accept browser-produced raster images and recordings, never active content."""
    if media_type == MediaType.SCREENSHOT:
        return (
            (mime_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (mime_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
            or (mime_type == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        )
    return (
        (mime_type.split(";", 1)[0] == "audio/webm" and data.startswith(b"\x1a\x45\xdf\xa3"))
        or (mime_type.split(";", 1)[0] == "audio/ogg" and data.startswith(b"OggS"))
        or (mime_type == "audio/mp4" and data[4:8] == b"ftyp")
        or (mime_type == "audio/wav" and data.startswith(b"RIFF") and data[8:12] == b"WAVE")
    )


def get_storage() -> FeedbackStorageProtocol:
    """Dependency to get storage instance. Override in main app."""
    raise NotImplementedError("Storage dependency not configured")


def get_max_upload_bytes() -> int:
    """Dependency for the per-file upload ceiling, in bytes.

    Standalone, this is the module's own UI_FEEDBACK_MAX_FILE_SIZE. A host
    application that mounts this router overrides it (see
    ``create_feedback_router``) so the limit comes from the host's settings
    and there is exactly one place it is configured.
    """
    return settings.max_file_size


def _reject_if_too_large(size: int, max_upload_bytes: int) -> None:
    """Raise 413 when a file exceeds the ceiling."""
    if size > max_upload_bytes:
        max_mb = max_upload_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {max_mb:.1f}MB",
        )


@router.post("", response_model=MediaItem, status_code=201)
async def upload_media(
    feedback_id: UUID,
    file: UploadFile = File(...),
    media_type: MediaType = Form(...),
    storage: FeedbackStorageProtocol = Depends(get_storage),
    max_upload_bytes: int = Depends(get_max_upload_bytes),
) -> MediaItem:
    """Upload a media file (screenshot or voice note)."""
    # Check feedback exists
    feedback = await storage.get_feedback(feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    # Refuse on the DECLARED size before reading, so an oversized upload is
    # not spooled in full just to be rejected. Starlette does not always
    # populate `size`, so the read below is still checked - this is an early
    # out, not the authoritative check.
    if file.size is not None:
        _reject_if_too_large(file.size, max_upload_bytes)

    data = await file.read()
    _reject_if_too_large(len(data), max_upload_bytes)

    # Validate both declared MIME type and bytes. SVG/HTML must never be
    # served inline from the dashboard origin.
    mime_type = file.content_type or "application/octet-stream"
    if not _valid_media(mime_type, data, media_type):
        raise HTTPException(status_code=400, detail="Unsupported media format")

    # Store media
    return await storage.create_media(
        feedback_id=feedback_id,
        media_type=media_type.value,
        mime_type=mime_type,
        data=data,
        file_name=file.filename,
    )


@router.get("/{media_id}")
async def get_media(
    feedback_id: UUID,
    media_id: UUID,
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> Response:
    """Download a media file."""
    result = await storage.get_media(media_id)
    if not result:
        raise HTTPException(status_code=404, detail="Media not found")

    item, data = result

    # Verify media belongs to the feedback
    if item.feedback_id != feedback_id:
        raise HTTPException(status_code=404, detail="Media not found")

    return Response(
        content=data,
        media_type=item.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{item.id}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    feedback_id: UUID,
    media_id: UUID,
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> None:
    """Delete a media file."""
    # First check it exists and belongs to the feedback
    result = await storage.get_media(media_id)
    if not result:
        raise HTTPException(status_code=404, detail="Media not found")

    item, _ = result
    if item.feedback_id != feedback_id:
        raise HTTPException(status_code=404, detail="Media not found")

    await storage.delete_media(media_id)
