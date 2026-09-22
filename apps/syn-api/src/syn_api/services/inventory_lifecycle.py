"""Critical initialization for durable session discovery and local capture."""

import logging

from syn_api.types import Err, LifecycleError, Ok, Result

logger = logging.getLogger(__name__)


async def initialize_session_inventory() -> Result[None, LifecycleError]:
    """Fail startup if local capture cannot outlive API/workspace processes."""
    from syn_api._wiring_inventory import initialize_inventory_runtime

    try:
        await initialize_inventory_runtime()
    except Exception:
        logger.exception("Durable session inventory initialization failed")
        return Err(
            LifecycleError.CONNECTION_FAILED,
            message="Durable session inventory initialization failed",
        )
    return Ok(None)
