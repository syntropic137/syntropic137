"""Storage implementations for UI Feedback."""

from ui_feedback.storage.memory import InMemoryFeedbackStorage
from ui_feedback.storage.postgres import PostgresFeedbackStorage
from ui_feedback.storage.protocol import FeedbackStorageProtocol

__all__ = [
    "FeedbackStorageProtocol",
    "InMemoryFeedbackStorage",
    "PostgresFeedbackStorage",
]
