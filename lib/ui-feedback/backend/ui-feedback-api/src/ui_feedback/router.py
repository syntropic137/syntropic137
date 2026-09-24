"""Mountable FastAPI router for UI Feedback API.

This module provides a factory function to create a router that can be
mounted into an existing FastAPI application.

Example:
    from fastapi import FastAPI
    from ui_feedback.router import create_feedback_router
    from ui_feedback.storage.postgres import PostgresFeedbackStorage

    app = FastAPI()
    storage = PostgresFeedbackStorage("postgresql://...")

    @app.on_event("startup")
    async def startup():
        await storage.connect()

    @app.on_event("shutdown")
    async def shutdown():
        await storage.disconnect()

    feedback_router, overrides = create_feedback_router(storage)
    app.dependency_overrides.update(overrides)
    app.include_router(feedback_router, prefix="/api")
"""

from collections.abc import Callable

from fastapi import APIRouter

from ui_feedback.api import feedback as feedback_api
from ui_feedback.api import media as media_api
from ui_feedback.api import stats as stats_api
from ui_feedback.storage.protocol import FeedbackStorageProtocol

DependencyOverrides = dict[Callable[[], object], Callable[[], object]]


def create_feedback_router(
    storage: FeedbackStorageProtocol | Callable[[], FeedbackStorageProtocol],
    *,
    max_upload_bytes: int | None = None,
) -> tuple[APIRouter, DependencyOverrides]:
    """Create a FastAPI router with all feedback endpoints.

    Args:
        storage: Either a storage implementation, or a callable returning one
            per request. The callable form exists because a host application
            may decide per request whether the feature is available at all -
            it can raise there instead of having every route repeat the check.
        max_upload_bytes: Per-file upload ceiling for screenshots and voice
            notes. ``None`` keeps the module's own UI_FEEDBACK_MAX_FILE_SIZE,
            which is what the standalone app uses; a host application passes
            its own so the limit is configured in exactly one place.

    Returns:
        Tuple of (router, dependency_overrides dict).
        The dependency_overrides should be merged into app.dependency_overrides.
    """
    router = APIRouter()

    # Storage implementations are objects, never callables, so this is an
    # unambiguous discrimination between the two accepted forms.
    if callable(storage):
        get_storage = storage
    else:
        instance = storage

        def get_storage() -> FeedbackStorageProtocol:
            return instance

    # `/feedback/stats` FIRST. Registration order is match order, and
    # `/feedback/{feedback_id}` would otherwise swallow it and fail to parse
    # "stats" as a UUID.
    router.include_router(stats_api.router)
    router.include_router(feedback_api.router)
    router.include_router(media_api.router)

    # Return overrides to be applied at app level
    overrides: DependencyOverrides = {
        feedback_api.get_storage: get_storage,
        media_api.get_storage: get_storage,
        stats_api.get_storage: get_storage,
    }

    if max_upload_bytes is not None:
        limit = max_upload_bytes

        def get_max_upload_bytes() -> int:
            return limit

        overrides[media_api.get_max_upload_bytes] = get_max_upload_bytes

    return router, overrides
