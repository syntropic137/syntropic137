"""API endpoints for UI Feedback."""

from ui_feedback.api.feedback import router as feedback_router
from ui_feedback.api.media import router as media_router
from ui_feedback.api.stats import router as stats_router

__all__ = [
    "feedback_router",
    "media_router",
    "stats_router",
]
