"""Standalone FastAPI application for UI Feedback API.

Run with:
    uv run uvicorn ui_feedback.main:app --reload --port 8001

Or:
    uv run python -m ui_feedback.main
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ui_feedback.api import feedback as feedback_api
from ui_feedback.api import media as media_api
from ui_feedback.api import stats as stats_api
from ui_feedback.config import settings
from ui_feedback.storage.memory import InMemoryFeedbackStorage
from ui_feedback.storage.postgres import PostgresFeedbackStorage
from ui_feedback.storage.protocol import FeedbackStorageProtocol

# Global storage instance
_storage: FeedbackStorageProtocol | None = None


def get_storage() -> FeedbackStorageProtocol:
    """Get the global storage instance."""
    if _storage is None:
        raise RuntimeError("Storage not initialized")
    return _storage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan - connect/disconnect storage."""
    global _storage

    # Use in-memory storage if explicitly set or if no database URL
    if settings.use_memory_storage or not settings.database_url:
        _storage = InMemoryFeedbackStorage()
        await _storage.connect()
        print("Using in-memory storage")
    else:
        _storage = PostgresFeedbackStorage(settings.database_url)
        await _storage.connect()
        print(f"Connected to database: {settings.database_url.split('@')[-1]}")

    try:
        yield
    finally:
        await _storage.disconnect()
        _storage = None
        print("Storage disconnected")


# Create FastAPI app
app = FastAPI(
    title="UI Feedback API",
    description="REST API for capturing and managing UI feedback",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
cors_origins = settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Override storage dependency
app.dependency_overrides[feedback_api.get_storage] = get_storage
app.dependency_overrides[media_api.get_storage] = get_storage
app.dependency_overrides[stats_api.get_storage] = get_storage

# Include routers - ORDER MATTERS!
# Stats must be before feedback to avoid /{feedback_id} matching "stats"
app.include_router(stats_api.router, prefix="/api")
app.include_router(feedback_api.router, prefix="/api")
app.include_router(media_api.router, prefix="/api")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with API info."""
    return {
        "name": "UI Feedback API",
        "version": "0.1.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "ui_feedback.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
