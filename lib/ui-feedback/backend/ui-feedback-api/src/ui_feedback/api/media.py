"""Media upload/download API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ui_feedback.config import settings
from ui_feedback.models import MediaItem, MediaType
from ui_feedback.storage.protocol import FeedbackStorageProtocol

router = APIRouter(prefix="/feedback/{feedback_id}/media", tags=["media"])


def get_storage() -> FeedbackStorageProtocol:
    """Dependency to get storage instance. Override in main app."""
    raise NotImplementedError("Storage dependency not configured")


@router.post("", response_model=MediaItem, status_code=201)
async def upload_media(
    feedback_id: UUID,
    file: UploadFile = File(...),
    media_type: MediaType = Form(...),
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> MediaItem:
    """Upload a media file (screenshot or voice note)."""
    # Check feedback exists
    feedback = await storage.get_feedback(feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    # Read file
    data = await file.read()

    # Check file size
    if len(data) > settings.max_file_size:
        max_mb = settings.max_file_size / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {max_mb:.1f}MB",
        )

    # Validate MIME type
    mime_type = file.content_type or "application/octet-stream"
    if media_type == MediaType.SCREENSHOT:
        if not mime_type.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail="Screenshots must be image files",
            )
    elif media_type == MediaType.VOICE_NOTE:
        if not mime_type.startswith("audio/"):
            raise HTTPException(
                status_code=400,
                detail="Voice notes must be audio files",
            )

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
            "Content-Disposition": f'inline; filename="{item.file_name or item.id}"',
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
