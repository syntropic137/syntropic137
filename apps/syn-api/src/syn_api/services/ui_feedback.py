"""In-app UI feedback (ADR-016, #105) — the one place the feature is decided.

The whole feature is a single runtime flag, ``SYN_UI_FEEDBACK_ENABLED``,
default off. Off is the open-source posture and it has to be genuinely
inert: no feedback tables are created, the routes answer a typed 404, and
the dashboard never fetches the widget chunk.

Everything that depends on the flag is decided here, once:

* whether the feature is on,
* which storage backs it (Postgres, or a refusal — never a silent
  in-memory fallback, ADR-060),
* whether the schema is applied at startup,
* what a route does when the feature is off.

The feedback extra is optional for standard API installs. Images built with
the extra mount the routes in both flag states so their OpenAPI contract stays
stable. The routes get storage from :func:`get_feedback_storage`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException
from ui_feedback.storage.memory import InMemoryFeedbackStorage
from ui_feedback.storage.postgres import PostgresFeedbackStorage

from syn_adapters.in_memory import assert_test_only

if TYPE_CHECKING:
    from ui_feedback.storage.protocol import FeedbackStorageProtocol

logger = logging.getLogger(__name__)

# Per-file ceiling for screenshots and voice notes. A full-page PNG at 4K is
# comfortably under this; a voice note is ~1 MB/minute at the widget's opus
# bitrate, so this is roughly a five-minute note. Enforced by the API on the
# declared size and again on the received bytes.
#
# The gateway accepts a 6 MB request body to allow multipart overhead.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class UiFeedbackConfigurationError(RuntimeError):
    """The feature is enabled but cannot be served durably."""


class TestOnlyFeedbackStorage(InMemoryFeedbackStorage):
    """In-memory feedback storage that refuses to exist in production.

    ADR-060: in-memory state is lost on restart, so feedback submitted
    against it disappears silently — the one failure mode that makes the
    whole feature worthless. The check runs at construction, so there is no
    path by which production ends up holding one of these.
    """

    def __init__(self) -> None:
        assert_test_only()
        super().__init__()


def is_enabled() -> bool:
    """Whether the UI feedback feature is switched on for this process."""
    from syn_shared.settings import get_settings

    return get_settings().syn_ui_feedback_enabled


def _build_storage() -> FeedbackStorageProtocol:
    """Choose a backend, or refuse.

    Postgres when there is a durable URL. In-memory ONLY in test/offline,
    and even then via a class that re-checks. Otherwise: fail fast. There
    is deliberately no third branch that degrades to in-memory when the
    database is merely absent — that is the silent data-loss path ADR-060
    exists to close.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()
    db_url = settings.syn_observability_db_url
    if db_url is not None:
        return PostgresFeedbackStorage(str(db_url))

    if settings.uses_in_memory_stores:
        return TestOnlyFeedbackStorage()

    raise UiFeedbackConfigurationError(
        "SYN_UI_FEEDBACK_ENABLED is true but SYN_OBSERVABILITY_DB_URL is not set. "
        "UI feedback needs a durable database; refusing to start it with "
        "in-memory storage, which would drop every item on restart."
    )


_storage: FeedbackStorageProtocol | None = None


async def connect() -> None:
    """Build the storage and apply the feedback schema. No-op when disabled.

    ``PostgresFeedbackStorage.connect()`` applies every migration in order
    and each statement is IF NOT EXISTS, so this converges an empty and an
    already-migrated database alike, on every boot.

    When the flag is off this does nothing at all — in particular it does
    not open a pool and does not create the tables.
    """
    global _storage

    if not is_enabled():
        logger.debug("UI feedback disabled — no storage, no schema")
        return

    if _storage is not None:
        return

    storage = _build_storage()
    await storage.connect()
    _storage = storage
    logger.info("UI feedback enabled (%s)", type(storage).__name__)


async def disconnect() -> None:
    """Release the storage, if one was built."""
    global _storage

    if _storage is None:
        return
    try:
        await _storage.disconnect()
    finally:
        _storage = None


def reset_for_tests() -> None:
    """Drop the process-local storage handle without touching the backend."""
    global _storage

    _storage = None


def get_feedback_storage() -> FeedbackStorageProtocol:
    """FastAPI dependency: the storage every feedback route runs against.

    This is also the gate. The routes are always mounted so the OpenAPI
    spec does not depend on configuration; their behaviour is decided here,
    in one place, rather than by a branch repeated in each route.
    """
    if not is_enabled():
        raise HTTPException(
            status_code=404,
            detail={
                "feature": "ui_feedback",
                "reason": "The in-app feedback feature is disabled on this deployment.",
                "enable_with": "SYN_UI_FEEDBACK_ENABLED=true",
            },
        )

    if _storage is None:
        raise HTTPException(
            status_code=503,
            detail={
                "feature": "ui_feedback",
                "reason": "The in-app feedback storage is not connected yet.",
                "enable_with": "SYN_UI_FEEDBACK_ENABLED=true",
            },
        )

    return _storage
