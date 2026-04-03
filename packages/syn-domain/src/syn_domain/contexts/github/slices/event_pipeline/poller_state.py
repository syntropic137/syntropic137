"""Adaptive polling interval state machine (ISS-386).

The poller switches between two modes based on webhook health:

- **ACTIVE_POLLING**: No webhooks arriving — poll at the base interval
  (default 60s) to ensure events are captured.
- **SAFETY_NET**: Webhooks are healthy — poll infrequently (default 300s)
  as a catch-up safety net.

Errors (rate limits, network failures) trigger exponential backoff
within the current mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class PollerMode(StrEnum):
    """Polling mode determined by webhook health."""

    ACTIVE_POLLING = "active_polling"
    SAFETY_NET = "safety_net"


@dataclass
class PollerState:
    """Adaptive polling interval state machine."""

    base_interval: float = 60.0
    """Interval in ACTIVE_POLLING mode (seconds)."""

    safety_interval: float = 300.0
    """Interval in SAFETY_NET mode (seconds)."""

    max_backoff: float = 600.0
    """Maximum interval regardless of mode or errors (seconds)."""

    mode: PollerMode = field(default=PollerMode.ACTIVE_POLLING)
    consecutive_errors: int = field(default=0)

    def update_mode(self, webhook_stale: bool) -> None:
        """Transition mode based on webhook health."""
        new_mode = PollerMode.ACTIVE_POLLING if webhook_stale else PollerMode.SAFETY_NET
        if new_mode != self.mode:
            logger.info("Poller mode: %s -> %s", self.mode.value, new_mode.value)
            self.mode = new_mode
            self.consecutive_errors = 0

    def record_error(self) -> None:
        """Record a polling error to increase backoff."""
        self.consecutive_errors += 1

    def record_success(self) -> None:
        """Reset backoff on successful poll."""
        self.consecutive_errors = 0

    @property
    def current_interval(self) -> float:
        """Compute the current poll interval in seconds.

        Uses the mode's base interval multiplied by exponential backoff
        from consecutive errors, capped at ``max_backoff``.
        """
        base = (
            self.base_interval if self.mode == PollerMode.ACTIVE_POLLING else self.safety_interval
        )
        multiplier = 2**self.consecutive_errors
        return min(base * multiplier, self.max_backoff)
