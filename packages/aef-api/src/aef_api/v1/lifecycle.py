"""Lifecycle operations — startup, shutdown, and health checks.

Centralizes application lifecycle management so the dashboard
can delegate to aef_api instead of importing adapters directly.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

from aef_api._wiring import (
    disconnect,
    ensure_connected,
    get_event_store_instance,
    get_github_settings,
    get_realtime,
    get_subscription_coordinator,
)
from aef_api.types import Err, LifecycleError, Ok, Result

if TYPE_CHECKING:
    from typing import Any

    from aef_api.auth import AuthContext

logger = logging.getLogger(__name__)

# Module-level reference to the subscription service
_subscription_service: Any = None


async def startup(
    skip_validation: bool = False,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, LifecycleError]:
    """Initialize the application: connect to event store, start subscriptions.

    Args:
        skip_validation: Skip credential validation (for test mode).
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(LifecycleError) on failure.
    """
    global _subscription_service

    try:
        from aef_shared.settings import get_settings

        settings = get_settings()

        # Validate credentials (unless skipped or in test mode)
        if not skip_validation and not settings.is_test:
            result = validate_credentials()
            if isinstance(result, Err):
                return result

        # Skip subscription service in test environment
        if settings.is_test:
            return Ok(None)

        # Initialize AgentEventStore
        try:
            event_store = get_event_store_instance()
            await event_store.initialize()
        except Exception:
            logger.exception("Failed to initialize AgentEventStore")

        # Connect to event store
        await ensure_connected()

        # Start subscription coordinator
        try:
            realtime = get_realtime()
            _subscription_service = get_subscription_coordinator(
                realtime_projection=realtime,
            )
            await _subscription_service.start()
        except Exception:
            logger.exception("Failed to start subscription coordinator")

        return Ok(None)
    except Exception as e:
        return Err(LifecycleError.CONNECTION_FAILED, message=str(e))


async def shutdown(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, LifecycleError]:
    """Gracefully shut down: stop subscriptions, disconnect from event store.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(LifecycleError) on failure.
    """
    global _subscription_service

    try:
        if _subscription_service is not None:
            with contextlib.suppress(Exception):
                await _subscription_service.stop()
            _subscription_service = None

        await disconnect()
        return Ok(None)
    except Exception as e:
        return Err(LifecycleError.CONNECTION_FAILED, message=str(e))


async def health_check(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[dict, LifecycleError]:
    """Check application health.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(dict) with health status.
    """
    response: dict = {"status": "healthy"}

    if _subscription_service is not None:
        try:
            response["subscription"] = _subscription_service.get_status()
        except Exception:
            response["subscription"] = {"status": "unknown"}

    return Ok(response)


def validate_credentials(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, LifecycleError]:
    """Validate required API keys and GitHub App configuration.

    Exports ANTHROPIC_API_KEY to os.environ for agent adapters.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(LifecycleError) on failure.
    """
    from aef_shared.settings import get_settings

    settings = get_settings()

    # Validate Anthropic API key
    api_key = settings.anthropic_api_key
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key.get_secret_value()
    elif not settings.is_test and settings.app_environment != "development":
        return Err(
            LifecycleError.VALIDATION_FAILED,
            message="ANTHROPIC_API_KEY is required",
        )

    # Validate GitHub App
    try:
        github = get_github_settings()
        if (
            not github.is_configured
            and not settings.is_test
            and settings.app_environment == "development"
        ):
            return Err(
                LifecycleError.VALIDATION_FAILED,
                message="GitHub App is REQUIRED but not configured",
            )
    except Exception:
        logger.exception("Failed to validate GitHub App configuration")

    return Ok(None)
