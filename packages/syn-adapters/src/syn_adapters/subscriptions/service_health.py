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

    # Get saved position from store
    try:
        saved_position = await svc._projection_store.get_position(SUBSCRIPTION_POSITION_KEY)
        if saved_position is None:
            saved_position = 0
    except Exception as e:
        saved_position = -1
        warnings_list.append(f"Failed to read saved position: {e}")

    # Check for position gaps
    position_gap = abs(svc._last_position - (saved_position or 0))

    # If there's a large gap between memory and saved, something might be wrong
    if position_gap > svc._batch_size * 2:
        warnings_list.append(
            f"Large gap between saved position ({saved_position}) "
            f"and in-memory position ({svc._last_position})"
        )

    # Check if service is running but not processing
    if svc._running and not svc._caught_up:
        time_since_event = None
        if svc._last_event_time:
            time_since_event = (datetime.now(UTC) - svc._last_event_time).total_seconds()
            if time_since_event > 60:  # No events for 60+ seconds
                warnings_list.append(f"Running but no events processed for {time_since_event:.0f}s")

    # Check reconnect count (many reconnects might indicate problems)
    if svc._reconnect_count > 10:
        warnings_list.append(
            f"High reconnect count ({svc._reconnect_count}) - "
            "possible connectivity or event store issues"
        )

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
