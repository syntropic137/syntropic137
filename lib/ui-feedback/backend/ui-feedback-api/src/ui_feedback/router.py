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

from typing import Callable

from fastapi import APIRouter

from ui_feedback.api import feedback as feedback_api
from ui_feedback.api import media as media_api
from ui_feedback.api import stats as stats_api
from ui_feedback.storage.protocol import FeedbackStorageProtocol


def create_feedback_router(
    storage: FeedbackStorageProtocol,
) -> tuple[APIRouter, dict[Callable[[], FeedbackStorageProtocol], Callable[[], FeedbackStorageProtocol]]]:
    """Create a FastAPI router with all feedback endpoints.

    Args:
        storage: Storage implementation to use for persistence.

    Returns:
        Tuple of (router, dependency_overrides dict).
        The dependency_overrides should be merged into app.dependency_overrides.
    """
    router = APIRouter()

    # Create storage dependency
    def get_storage() -> FeedbackStorageProtocol:
        return storage

    # Include all routers
    router.include_router(feedback_api.router)
    router.include_router(media_api.router)
    router.include_router(stats_api.router)

    # Return overrides to be applied at app level
    overrides: dict[Callable[[], FeedbackStorageProtocol], Callable[[], FeedbackStorageProtocol]] = {
        feedback_api.get_storage: get_storage,
        media_api.get_storage: get_storage,
        stats_api.get_storage: get_storage,
    }

    return router, overrides
