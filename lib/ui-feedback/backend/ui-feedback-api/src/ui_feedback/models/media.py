"""Pydantic models for media attachments."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MediaType(str, Enum):
    """Type of media attachment."""

    SCREENSHOT = "screenshot"
    VOICE_NOTE = "voice_note"


class MediaCreate(BaseModel):
    """Request model for creating media (metadata only, file sent separately)."""

    media_type: MediaType = Field(..., description="Type of media")
    mime_type: str = Field(..., description="MIME type of the file")
    file_name: str | None = Field(None, description="Original file name")

    model_config = ConfigDict(use_enum_values=True)


class MediaItem(BaseModel):
    """Response model for a media item."""

    id: UUID
    feedback_id: UUID
    media_type: MediaType
    mime_type: str
    file_name: str | None = None
    file_size: int | None = None
    external_url: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
