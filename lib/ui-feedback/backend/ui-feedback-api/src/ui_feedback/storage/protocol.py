"""Abstract storage protocol for UI Feedback."""

from abc import ABC, abstractmethod
from uuid import UUID

from ui_feedback.models import (
    FeedbackCreate,
    FeedbackItem,
    FeedbackItemWithMedia,
    FeedbackStats,
    FeedbackUpdate,
    MediaItem,
)


class FeedbackStorageProtocol(ABC):
    """Abstract interface for feedback storage implementations."""

    # =========================================================
    # Feedback CRUD
    # =========================================================

    @abstractmethod
    async def create_feedback(self, data: FeedbackCreate) -> FeedbackItem:
        """Create a new feedback item."""
        ...

    @abstractmethod
    async def get_feedback(self, feedback_id: UUID) -> FeedbackItemWithMedia | None:
        """Get a single feedback item with media metadata."""
        ...

    @abstractmethod
    async def list_feedback(
        self,
        *,
        status: str | None = None,
        feedback_type: str | None = None,
        priority: str | None = None,
        app_name: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> tuple[list[FeedbackItem], int]:
        """List feedback items with filtering and pagination.

        Returns:
            Tuple of (items, total_count)
        """
        ...

    @abstractmethod
    async def update_feedback(
        self, feedback_id: UUID, data: FeedbackUpdate
    ) -> FeedbackItem | None:
        """Update a feedback item."""
        ...

    @abstractmethod
    async def delete_feedback(self, feedback_id: UUID) -> bool:
        """Delete a feedback item and all associated media."""
        ...

    # =========================================================
    # Media CRUD
    # =========================================================

    @abstractmethod
    async def create_media(
        self,
        feedback_id: UUID,
        media_type: str,
        mime_type: str,
        data: bytes,
        file_name: str | None = None,
    ) -> MediaItem:
        """Create a new media attachment."""
        ...

    @abstractmethod
    async def get_media(self, media_id: UUID) -> tuple[MediaItem, bytes] | None:
        """Get media item with binary data."""
        ...

    @abstractmethod
    async def delete_media(self, media_id: UUID) -> bool:
        """Delete a media attachment."""
        ...

    # =========================================================
    # Stats
    # =========================================================

    @abstractmethod
    async def get_stats(self, app_name: str | None = None) -> FeedbackStats:
        """Get aggregate statistics."""
        ...

    # =========================================================
    # Connection management
    # =========================================================

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection to storage."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to storage."""
        ...
