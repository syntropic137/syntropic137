"""Webhook health tracker — detects stale webhook delivery for poller mode switching."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_DEFAULT_STALE_THRESHOLD_SECONDS = 1800.0  # 30 minutes


class WebhookHealthTracker:
    """Tracks webhook delivery freshness.

    When no webhook has been received within the stale threshold, the
    poller switches to ``ACTIVE_POLLING`` mode for more aggressive polling.
    """

    def __init__(
        self,
        stale_threshold: float = _DEFAULT_STALE_THRESHOLD_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._last_received_at: float | None = None
        self._stale_threshold = stale_threshold
        self._clock = clock or time.monotonic

    def record_received(self) -> None:
        """Record that a webhook was just received."""
        self._last_received_at = self._clock()

    @property
    def is_stale(self) -> bool:
        """``True`` if no webhook received within the stale threshold."""
        if self._last_received_at is None:
            return True  # Never received → assume stale
        return (self._clock() - self._last_received_at) > self._stale_threshold

    @property
    def seconds_since_last(self) -> float | None:
        """Seconds since last webhook, or ``None`` if never received."""
        if self._last_received_at is None:
            return None
        return self._clock() - self._last_received_at
