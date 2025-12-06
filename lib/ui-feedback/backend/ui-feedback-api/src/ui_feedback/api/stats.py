"""Statistics API endpoints."""

from fastapi import APIRouter, Depends, Query

from ui_feedback.models import FeedbackStats
from ui_feedback.storage.protocol import FeedbackStorageProtocol

router = APIRouter(prefix="/feedback", tags=["stats"])


def get_storage() -> FeedbackStorageProtocol:
    """Dependency to get storage instance. Override in main app."""
    raise NotImplementedError("Storage dependency not configured")


@router.get("/stats", response_model=FeedbackStats)
async def get_stats(
    app_name: str | None = Query(None, alias="app", description="Filter by app name"),
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> FeedbackStats:
    """Get aggregate statistics for feedback items."""
    return await storage.get_stats(app_name=app_name)
