"""Feedback CRUD API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ui_feedback.models import (
    FeedbackCreate,
    FeedbackItem,
    FeedbackItemWithMedia,
    FeedbackList,
    FeedbackUpdate,
)
from ui_feedback.storage.protocol import FeedbackStorageProtocol

router = APIRouter(prefix="/feedback", tags=["feedback"])


def get_storage() -> FeedbackStorageProtocol:
    """Dependency to get storage instance. Override in main app."""
    raise NotImplementedError("Storage dependency not configured")


@router.get("", response_model=FeedbackList)
async def list_feedback(
    status: str | None = Query(None, description="Filter by status"),
    feedback_type: str | None = Query(None, alias="type", description="Filter by type"),
    priority: str | None = Query(None, description="Filter by priority"),
    app_name: str | None = Query(None, alias="app", description="Filter by app name"),
    search: str | None = Query(None, description="Search in comments"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, alias="limit", description="Items per page"),
    order_by: str = Query("created_at", description="Field to order by"),
    order_desc: bool = Query(True, alias="desc", description="Order descending"),
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> FeedbackList:
    """List all feedback items with optional filtering."""
    items, total = await storage.list_feedback(
        status=status,
        feedback_type=feedback_type,
        priority=priority,
        app_name=app_name,
        search=search,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_desc=order_desc,
    )
    return FeedbackList(items=items, total=total, page=page, page_size=page_size)


@router.get("/{feedback_id}", response_model=FeedbackItemWithMedia)
async def get_feedback(
    feedback_id: UUID,
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> FeedbackItemWithMedia:
    """Get a single feedback item with media metadata."""
    item = await storage.get_feedback(feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return item


@router.post("", response_model=FeedbackItem, status_code=201)
async def create_feedback(
    data: FeedbackCreate,
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> FeedbackItem:
    """Create a new feedback item."""
    return await storage.create_feedback(data)


@router.patch("/{feedback_id}", response_model=FeedbackItem)
async def update_feedback(
    feedback_id: UUID,
    data: FeedbackUpdate,
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> FeedbackItem:
    """Update a feedback item (status, priority, assignment, notes)."""
    item = await storage.update_feedback(feedback_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return item


@router.delete("/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: UUID,
    storage: FeedbackStorageProtocol = Depends(get_storage),
) -> None:
    """Delete a feedback item and all associated media."""
    deleted = await storage.delete_feedback(feedback_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feedback not found")
