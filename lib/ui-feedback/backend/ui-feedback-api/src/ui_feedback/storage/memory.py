"""In-memory storage implementation for testing."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from ui_feedback.models import (
    FeedbackCreate,
    FeedbackItem,
    FeedbackItemWithMedia,
    FeedbackStats,
    FeedbackUpdate,
    MediaItem,
    MediaSummary,
    PriorityCount,
    StatusCount,
    TypeCount,
)
from ui_feedback.storage.protocol import FeedbackStorageProtocol


class InMemoryFeedbackStorage(FeedbackStorageProtocol):
    """In-memory storage for testing purposes."""

    def __init__(self) -> None:
        self._feedback: dict[UUID, dict] = {}
        self._media: dict[UUID, dict] = {}

    async def connect(self) -> None:
        """No-op for in-memory storage."""
        pass

    async def disconnect(self) -> None:
        """No-op for in-memory storage."""
        pass

    async def create_feedback(self, data: FeedbackCreate) -> FeedbackItem:
        """Create a new feedback item."""
        now = datetime.now(timezone.utc)
        feedback_id = uuid4()

        record = {
            "id": feedback_id,
            "url": data.url,
            "route": data.route,
            "viewport_width": data.viewport_width,
            "viewport_height": data.viewport_height,
            "click_x": data.click_x,
            "click_y": data.click_y,
            "css_selector": data.css_selector,
            "xpath": data.xpath,
            "component_name": data.component_name,
            "feedback_type": data.feedback_type,
            "comment": data.comment,
            "status": "open",
            "priority": data.priority,
            "assigned_to": None,
            "resolution_notes": None,
            "app_name": data.app_name,
            "app_version": data.app_version,
            "user_agent": data.user_agent,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }

        self._feedback[feedback_id] = record
        return FeedbackItem(**record, media_count=0)

    async def get_feedback(self, feedback_id: UUID) -> FeedbackItemWithMedia | None:
        """Get a single feedback item with media metadata."""
        record = self._feedback.get(feedback_id)
        if not record:
            return None

        media = [
            MediaSummary(
                id=m["id"],
                media_type=m["media_type"],
                mime_type=m["mime_type"],
                file_name=m["file_name"],
                file_size=m["file_size"],
                created_at=m["created_at"],
            )
            for m in self._media.values()
            if m["feedback_id"] == feedback_id
        ]

        return FeedbackItemWithMedia(**record, media_count=len(media), media=media)

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
        """List feedback items with filtering and pagination."""
        items = list(self._feedback.values())

        # Apply filters
        if status:
            items = [i for i in items if i["status"] == status]
        if feedback_type:
            items = [i for i in items if i["feedback_type"] == feedback_type]
        if priority:
            items = [i for i in items if i["priority"] == priority]
        if app_name:
            items = [i for i in items if i["app_name"] == app_name]
        if search:
            items = [i for i in items if search.lower() in (i["comment"] or "").lower()]

        # Sort
        reverse = order_desc
        items.sort(key=lambda x: x.get(order_by, x["created_at"]), reverse=reverse)

        total = len(items)

        # Paginate
        start = (page - 1) * page_size
        end = start + page_size
        items = items[start:end]

        # Convert to models
        result = []
        for record in items:
            media_count = sum(
                1 for m in self._media.values() if m["feedback_id"] == record["id"]
            )
            result.append(FeedbackItem(**record, media_count=media_count))

        return result, total

    async def update_feedback(
        self, feedback_id: UUID, data: FeedbackUpdate
    ) -> FeedbackItem | None:
        """Update a feedback item."""
        record = self._feedback.get(feedback_id)
        if not record:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                record[field] = value

        record["updated_at"] = datetime.now(timezone.utc)

        if data.status == "resolved":
            record["resolved_at"] = datetime.now(timezone.utc)

        media_count = sum(
            1 for m in self._media.values() if m["feedback_id"] == feedback_id
        )
        return FeedbackItem(**record, media_count=media_count)

    async def delete_feedback(self, feedback_id: UUID) -> bool:
        """Delete a feedback item and all associated media."""
        if feedback_id not in self._feedback:
            return False

        del self._feedback[feedback_id]

        # Delete associated media
        media_to_delete = [
            mid for mid, m in self._media.items() if m["feedback_id"] == feedback_id
        ]
        for mid in media_to_delete:
            del self._media[mid]

        return True

    async def create_media(
        self,
        feedback_id: UUID,
        media_type: str,
        mime_type: str,
        data: bytes,
        file_name: str | None = None,
    ) -> MediaItem:
        """Create a new media attachment."""
        media_id = uuid4()
        now = datetime.now(timezone.utc)

        record = {
            "id": media_id,
            "feedback_id": feedback_id,
            "media_type": media_type,
            "mime_type": mime_type,
            "file_name": file_name,
            "file_size": len(data),
            "data": data,
            "external_url": None,
            "created_at": now,
        }

        self._media[media_id] = record

        return MediaItem(
            id=media_id,
            feedback_id=feedback_id,
            media_type=media_type,
            mime_type=mime_type,
            file_name=file_name,
            file_size=len(data),
            external_url=None,
            created_at=now,
        )

    async def get_media(self, media_id: UUID) -> tuple[MediaItem, bytes] | None:
        """Get media item with binary data."""
        record = self._media.get(media_id)
        if not record:
            return None

        item = MediaItem(
            id=record["id"],
            feedback_id=record["feedback_id"],
            media_type=record["media_type"],
            mime_type=record["mime_type"],
            file_name=record["file_name"],
            file_size=record["file_size"],
            external_url=record["external_url"],
            created_at=record["created_at"],
        )
        return item, record["data"]

    async def delete_media(self, media_id: UUID) -> bool:
        """Delete a media attachment."""
        if media_id not in self._media:
            return False
        del self._media[media_id]
        return True

    async def get_stats(self, app_name: str | None = None) -> FeedbackStats:
        """Get aggregate statistics."""
        items = list(self._feedback.values())

        if app_name:
            items = [i for i in items if i["app_name"] == app_name]

        by_status = StatusCount()
        by_type = TypeCount()
        by_priority = PriorityCount()
        by_app: dict[str, int] = {}

        for item in items:
            # Count by status
            status = item["status"]
            current = getattr(by_status, status, 0)
            setattr(by_status, status, current + 1)

            # Count by type
            ftype = item["feedback_type"]
            current = getattr(by_type, ftype, 0)
            setattr(by_type, ftype, current + 1)

            # Count by priority
            prio = item["priority"]
            current = getattr(by_priority, prio, 0)
            setattr(by_priority, prio, current + 1)

            # Count by app
            app = item["app_name"]
            by_app[app] = by_app.get(app, 0) + 1

        return FeedbackStats(
            total=len(items),
            by_status=by_status,
            by_type=by_type,
            by_priority=by_priority,
            by_app=by_app if not app_name else {},
        )
