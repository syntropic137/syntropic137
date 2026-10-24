"""Critical initialization for durable session discovery and local capture.

Kept out of lifecycle.py the way feedback_lifecycle.py is: lifecycle owns the
startup sequence, this module owns what the session inventory needs from it.
"""

import logging
from typing import Protocol

from syn_api.types import Err, LifecycleError, Ok, Result

logger = logging.getLogger(__name__)


class _Stoppable(Protocol):
    async def stop(self) -> None: ...


async def initialize_session_inventory() -> Result[None, LifecycleError]:
    """Fail startup if local capture cannot outlive API/workspace processes."""
    from syn_api._wiring_inventory import initialize_inventory_runtime

    try:
        await initialize_inventory_runtime()
    except Exception as e:
        logger.exception("Durable session inventory initialization failed")
        # The cause rides in the message: under a restart loop the traceback
        # above scrolls out of `docker logs --tail`, the abort line does not (#1511).
        return Err(
            LifecycleError.CONNECTION_FAILED,
            message=f"Durable session inventory initialization failed: {type(e).__name__}: {e}",
        )
    return Ok(None)


async def start_inventory_clock(coordinator: _Stoppable) -> None:
    """Start the inventory sweep clock, stopping `coordinator` if that fails.

    Runs after the coordinator has started, so a failure here must undo that
    start before re-raising; otherwise the recovery loop would start a second
    coordinator on top of an orphaned one.
    """
    from syn_api._wiring_inventory import get_inventory_runtime

    try:
        await get_inventory_runtime().clock.start()
    except Exception:
        await coordinator.stop()
        raise


async def stop_session_inventory() -> None:
    """Stop the inventory clock and replication; a no-op if never started."""
    from syn_api._wiring_inventory import stop_inventory_runtime

    await stop_inventory_runtime()
