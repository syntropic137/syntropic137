"""Lifecycle operations — startup, shutdown, and health checks.

Centralizes application lifecycle management so the dashboard
can delegate to syn_api instead of importing adapters directly.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_api._wiring import (
    disconnect,
    ensure_connected,
    get_event_store_instance,
    get_realtime,
    get_subscription_coordinator,
    get_workflow_dispatcher,
)
from syn_api.services.credentials import validate_credentials
from syn_api.services.reconciliation import cleanup_orphaned_containers, reconcile_orphaned_sessions
from syn_api.services.seeding import seed_offline_data
from syn_api.types import Err, LifecycleError, Ok, Result

if TYPE_CHECKING:
    from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
    from syn_api._wiring import BackgroundWorkflowDispatcher
    from syn_api.auth import AuthContext
    from syn_api.services.github_event_poller import GitHubEventPoller

logger = logging.getLogger(__name__)


@dataclass
class LifecycleState:
    """Mutable state managed across startup / shutdown / health_check."""

    subscription_service: CoordinatorSubscriptionService | None = None
    workflow_dispatcher: BackgroundWorkflowDispatcher | None = None
    event_poller: GitHubEventPoller | None = None
    degraded_reasons: list[str] = field(default_factory=list)


_state = LifecycleState()


# ── Public API ──────────────────────────────────────────────────────


async def startup(
    skip_validation: bool = False,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[dict, LifecycleError]:
    """Initialize the application: connect to event store, start subscriptions.

    Startup sequence (order matters):
      1. Event store connection (CRITICAL — abort on failure)
      2. Artifact storage bucket (DEGRADED — warn and continue)
      3. Subscription coordinator (DEGRADED — warn and continue)
      4. GitHub event poller (DEGRADED — warn and continue)
      5. Orphan reconciliation (always runs)

    Critical failures (event store, DB) abort startup.
    Degraded failures (GitHub, Anthropic, Redis, subscriptions) warn and continue.

    Args:
        skip_validation: Skip credential validation (for test mode).
        auth: Optional authentication context.

    Returns:
        Ok({"mode": "full"|"degraded", ...}) on success,
        Err(LifecycleError) on critical failure.
    """
    _state.degraded_reasons = []

    from syn_shared.settings import get_settings

    settings = get_settings()

    if not skip_validation and not settings.uses_in_memory_stores:
        validate_credentials(_state.degraded_reasons)

    if settings.is_test:
        return Ok({"mode": "full"})

    if settings.is_offline:
        await seed_offline_data()
        return Ok({"mode": "full"})

    # Critical path — abort on failure
    result = await _init_event_store()
    if isinstance(result, Err):
        return result

    # Degraded path — warn and continue
    await _init_subscriptions(_state)
    await _init_event_poller(_state)
    await reconcile_orphaned_sessions()
    await cleanup_orphaned_containers()

    mode = "degraded" if _state.degraded_reasons else "full"
    return Ok({"mode": mode, "degraded_reasons": _state.degraded_reasons})


async def shutdown(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, LifecycleError]:
    """Gracefully shut down: stop subscriptions, disconnect from event store.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(LifecycleError) on failure.
    """
    try:
        if _state.event_poller is not None:
            with contextlib.suppress(Exception):
                await _state.event_poller.stop()
            _state.event_poller = None

        if _state.workflow_dispatcher is not None:
            with contextlib.suppress(Exception):
                await _state.workflow_dispatcher.shutdown()
            _state.workflow_dispatcher = None

        if _state.subscription_service is not None:
            with contextlib.suppress(Exception):
                await _state.subscription_service.stop()
            _state.subscription_service = None

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
        Ok(dict) with health status including mode (full/degraded).
    """
    mode = "degraded" if _state.degraded_reasons else "full"
    response: dict = {"status": "healthy", "mode": mode}

    if _state.degraded_reasons:
        response["degraded_reasons"] = _state.degraded_reasons

    _enrich_subscription_health(response, mode)

    return Ok(response)


# ── Private helpers ─────────────────────────────────────────────────


async def _init_event_store() -> Result[None, LifecycleError]:
    """Initialize event store and verify connection (critical)."""
    try:
        event_store = get_event_store_instance()
        await event_store.initialize()
    except Exception as e:
        logger.exception("AgentEventStore initialization failed")
        return Err(
            LifecycleError.CONNECTION_FAILED,
            message=f"AgentEventStore initialization failed: {e}",
        )

    try:
        await ensure_connected()
    except Exception as e:
        logger.exception("Event store connection failed")
        return Err(
            LifecycleError.CONNECTION_FAILED,
            message=f"Event store connection failed: {e}",
        )

    return Ok(None)


def _enrich_subscription_health(response: dict, mode: str) -> None:
    """Add subscription coordinator status to the health response."""
    if _state.subscription_service is None:
        return

    try:
        sub_status = _state.subscription_service.get_status()
        sub_healthy = sub_status.get("running", False)
        response["subscription"] = {
            **sub_status,
            "status": "healthy" if sub_healthy else "degraded",
        }
        if not sub_healthy:
            response.setdefault("degraded_reasons", []).append("subscription_coordinator")
            if mode == "full":
                response["mode"] = "degraded"
    except Exception:
        response["subscription"] = {"status": "unknown"}


async def _init_subscriptions(state: LifecycleState) -> None:
    """Start subscription coordinator (degraded on failure)."""
    try:
        realtime = get_realtime()
        state.workflow_dispatcher = await get_workflow_dispatcher()
        coordinator = get_subscription_coordinator(
            realtime_projection=realtime,
            execution_service=state.workflow_dispatcher,
        )
        await coordinator.start()
        state.subscription_service = coordinator
    except Exception:
        logger.exception("Failed to start subscription coordinator (degraded mode)")
        state.degraded_reasons.append("subscription_coordinator")


async def _init_event_poller(state: LifecycleState) -> None:
    """Start the GitHub Events API poller (degraded on failure)."""
    from syn_shared.settings import get_settings

    settings = get_settings()

    if not settings.github.is_configured:
        logger.info("GitHub App not configured — event poller disabled")
        return

    if not settings.polling.enabled:
        logger.info("Event polling disabled by configuration")
        return

    try:
        from syn_adapters.github.client import get_github_client
        from syn_adapters.github.events_api_client import GitHubEventsAPIClient
        from syn_api._wiring import (
            get_event_pipeline,
            get_trigger_store,
            get_webhook_health_tracker,
        )
        from syn_api.services.github_event_poller import GitHubEventPoller

        events_client = GitHubEventsAPIClient(get_github_client())
        poller = GitHubEventPoller(
            events_client=events_client,
            pipeline=get_event_pipeline(),
            health_tracker=get_webhook_health_tracker(),
            trigger_store=get_trigger_store(),
            settings=settings.polling,
        )
        await poller.start()
        state.event_poller = poller
    except Exception:
        logger.exception("Failed to start event poller (degraded mode)")
        state.degraded_reasons.append("event_poller")
