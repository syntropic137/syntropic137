"""Pydantic models for feedback items."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeedbackType(str, Enum):
    """Type of feedback."""

    BUG = "bug"
    FEATURE = "feature"
    UI_UX = "ui_ux"
    PERFORMANCE = "performance"
    QUESTION = "question"
    OTHER = "other"


class Status(str, Enum):
    """Feedback ticket status."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    WONT_FIX = "wont_fix"


class Priority(str, Enum):
    """Feedback priority level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FeedbackCreate(BaseModel):
    """Request model for creating feedback."""

    # Location context
    url: str = Field(..., description="URL where feedback was created")
    route: str | None = Field(None, description="React Router path if available")
    viewport_width: int | None = Field(None, description="Viewport width in pixels")
    viewport_height: int | None = Field(None, description="Viewport height in pixels")
    click_x: int | None = Field(None, description="X coordinate of click")
    click_y: int | None = Field(None, description="Y coordinate of click")
    css_selector: str | None = Field(None, description="CSS selector of clicked element")
    xpath: str | None = Field(None, description="XPath of clicked element")
    component_name: str | None = Field(None, description="React component name")

    # Feedback content
    feedback_type: FeedbackType = Field(default=FeedbackType.BUG, description="Type of feedback")
    comment: str | None = Field(None, description="User's comment")

    # Optional metadata
    priority: Priority = Field(default=Priority.MEDIUM, description="Priority level")
    app_name: str = Field(..., description="Name of the application")
    app_version: str | None = Field(None, description="Version of the application")
    user_agent: str | None = Field(None, description="Browser user agent")

    # Environment context - for knowing where feedback came from
    environment: str | None = Field(None, description="Environment name (development, staging, production)")
    git_commit: str | None = Field(None, description="Git commit hash")
    git_branch: str | None = Field(None, description="Git branch name")
    hostname: str | None = Field(None, description="Hostname where the app is running")

    model_config = ConfigDict(use_enum_values=True)


class FeedbackUpdate(BaseModel):
    """Request model for updating feedback."""

    status: Status | None = Field(None, description="New status")
    priority: Priority | None = Field(None, description="New priority")
    assigned_to: str | None = Field(None, description="Assignee")
    resolution_notes: str | None = Field(None, description="Notes about resolution")
    comment: str | None = Field(None, description="Updated comment")

    model_config = ConfigDict(use_enum_values=True)


class FeedbackItem(BaseModel):
    """Response model for a feedback item (without media)."""

    id: UUID
    url: str
    route: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    click_x: int | None = None
    click_y: int | None = None
    css_selector: str | None = None
    xpath: str | None = None
    component_name: str | None = None

    feedback_type: FeedbackType
    comment: str | None = None

    status: Status
    priority: Priority
    assigned_to: str | None = None
    resolution_notes: str | None = None

    app_name: str
    app_version: str | None = None
    user_agent: str | None = None

    # Environment context
    environment: str | None = None
    git_commit: str | None = None
    git_branch: str | None = None
    hostname: str | None = None

    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None

    # Media count (not the actual media)
    media_count: int = 0

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class MediaSummary(BaseModel):
    """Summary of a media item (without binary data)."""

    id: UUID
    media_type: str
    mime_type: str
    file_name: str | None = None
    file_size: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedbackItemWithMedia(FeedbackItem):
    """Response model for a feedback item with media metadata."""

    media: list[MediaSummary] = []


class FeedbackList(BaseModel):
    """Response model for listing feedback items."""

    items: list[FeedbackItem]
    total: int
    page: int = 1
    page_size: int = 50


class StatusCount(BaseModel):
    """Count of items by status."""

    open: int = 0
    in_progress: int = 0
    resolved: int = 0
    closed: int = 0
    wont_fix: int = 0


class TypeCount(BaseModel):
    """Count of items by type."""

    bug: int = 0
    feature: int = 0
    ui_ux: int = 0
    performance: int = 0
    question: int = 0
    other: int = 0


class PriorityCount(BaseModel):
    """Count of items by priority."""

    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0


class FeedbackStats(BaseModel):
    """Aggregate statistics for feedback items."""

    total: int = 0
    by_status: StatusCount = Field(default_factory=StatusCount)
    by_type: TypeCount = Field(default_factory=TypeCount)
    by_priority: PriorityCount = Field(default_factory=PriorityCount)
    by_app: dict[str, int] = Field(default_factory=dict)
