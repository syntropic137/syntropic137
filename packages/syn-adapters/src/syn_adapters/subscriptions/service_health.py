"""Health check logic for EventSubscriptionService.

Extracted from service.py to reduce module complexity.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

from syn_adapters.subscriptions.service import SUBSCRIPTION_POSITION_KEY

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


async def _get_saved_position(
    svc: EventSubscriptionService,
    warnings_list: list[str],
) -> int:
    """Read saved position from the projection store, appending warnings on failure."""
    try:
        saved = await svc._projection_store.get_position(SUBSCRIPTION_POSITION_KEY)
        return saved if saved is not None else 0
    except Exception as e:
        warnings_list.append(f"Failed to read saved position: {e}")
        return -1


def _check_position_gap(
    svc: EventSubscriptionService,
    saved_position: int,
    warnings_list: list[str],
) -> int:
    """Check for large gaps between saved and in-memory positions."""
    position_gap = abs(svc._last_position - (saved_position or 0))
    if position_gap > svc._batch_size * 2:
        warnings_list.append(
            f"Large gap between saved position ({saved_position}) "
            f"and in-memory position ({svc._last_position})"
        )
    return position_gap


def _check_event_staleness(svc: EventSubscriptionService, warnings_list: list[str]) -> None:
    """Warn if the service is running but hasn't processed events recently."""
    if not (svc._running and not svc._caught_up):
        return
    if svc._last_event_time:
        time_since = (datetime.now(UTC) - svc._last_event_time).total_seconds()
        if time_since > 60:
            warnings_list.append(f"Running but no events processed for {time_since:.0f}s")


def _check_reconnect_count(svc: EventSubscriptionService, warnings_list: list[str]) -> None:
    """Warn if the reconnect count is suspiciously high."""
    if svc._reconnect_count > 10:
        warnings_list.append(
            f"High reconnect count ({svc._reconnect_count}) - "
            "possible connectivity or event store issues"
        )


async def health_check(svc: EventSubscriptionService) -> dict:
    """Perform health check for subscription service.

    This checks for consistency between saved position and the actual
    state of projections. Useful for detecting issues after crashes
    or unexpected shutdowns.

    Returns:
        Dictionary with health status:
        - healthy: bool - True if no issues detected
        - position_saved: int - Last saved position in projection_states
        - position_in_memory: int - Current position in memory
        - position_gap: int - Difference between saved and in-memory
        - warnings: list[str] - Any warnings detected
    """
    warnings_list: list[str] = []

    saved_position = await _get_saved_position(svc, warnings_list)
    position_gap = _check_position_gap(svc, saved_position, warnings_list)
    _check_event_staleness(svc, warnings_list)
    _check_reconnect_count(svc, warnings_list)

    health_status = {
        "healthy": len(warnings_list) == 0,
        "position_saved": saved_position,
        "position_in_memory": svc._last_position,
        "position_gap": position_gap,
        "events_processed": svc._events_processed,
        "reconnect_count": svc._reconnect_count,
        "is_running": svc._running,
        "is_caught_up": svc._caught_up,
        "warnings": warnings_list,
    }

    logger.log(
        logging.WARNING if warnings_list else logging.DEBUG,
        "[SUBSCRIPTION] Health check completed",
        extra=health_status,
    )

    return health_status
