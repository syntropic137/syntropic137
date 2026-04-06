"""Lifecycle operations — startup, shutdown, and health checks.

Centralizes application lifecycle management so the dashboard
can delegate to syn_api instead of importing adapters directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from enum import StrEnum
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


class DegradedReason(StrEnum):
    """Reasons the API may enter degraded mode.

    StrEnum so values serialize directly to JSON in health responses.
    """

    ARTIFACT_STORAGE = "artifact_storage"
    SUBSCRIPTION_COORDINATOR = "subscription_coordinator"
    EVENT_POLLER = "event_poller"
    ANTHROPIC_API_KEY = "anthropic_api_key"
    GITHUB_APP = "github_app"


# Subsystems that can be recovered by retrying after transient failures
# (e.g. MinIO not yet DNS-resolvable at startup).
_RECOVERABLE_REASONS: frozenset[DegradedReason] = frozenset(
    {
        DegradedReason.ARTIFACT_STORAGE,
        DegradedReason.SUBSCRIPTION_COORDINATOR,
    }
)


@dataclass
class LifecycleState:
    """Mutable state managed across startup / shutdown / health_check."""

    subscription_service: CoordinatorSubscriptionService | None = None
    workflow_dispatcher: BackgroundWorkflowDispatcher | None = None
    event_poller: GitHubEventPoller | None = None
    degraded_reasons: list[DegradedReason] = field(default_factory=list)
    _recovery_task: asyncio.Task[None] | None = None
    _shutting_down: bool = False


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
    await _init_artifact_storage(_state)
    await _init_subscriptions(_state)
    await _init_event_poller(_state)
    await reconcile_orphaned_sessions()
    await cleanup_orphaned_containers()

    # If any recoverable subsystem is degraded, start a background recovery loop.
    recoverable = [r for r in _state.degraded_reasons if r in _RECOVERABLE_REASONS]
    if recoverable:
        _state._recovery_task = asyncio.create_task(
            _recovery_loop(_state),
            name="lifecycle-recovery",
        )

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
        _state._shutting_down = True

        if _state._recovery_task is not None:
            _state._recovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _state._recovery_task
            _state._recovery_task = None

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
            response.setdefault("degraded_reasons", []).append(
                DegradedReason.SUBSCRIPTION_COORDINATOR
            )
            if mode == "full":
                response["mode"] = "degraded"
    except Exception:
        response["subscription"] = {"status": "unknown"}


async def _init_artifact_storage(state: LifecycleState) -> None:
    """Ensure artifact storage bucket exists at startup (degraded on failure)."""
    try:
        from syn_adapters.storage.artifact_storage.factory import get_artifact_storage

        storage = await get_artifact_storage()
        await storage.ensure_ready()
        logger.info("Artifact storage bucket verified")
    except Exception:
        logger.exception("Failed to initialize artifact storage bucket (degraded mode)")
        state.degraded_reasons.append(DegradedReason.ARTIFACT_STORAGE)


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
        state.degraded_reasons.append(DegradedReason.SUBSCRIPTION_COORDINATOR)


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
        state.degraded_reasons.append(DegradedReason.EVENT_POLLER)


def _get_recoverable(state: LifecycleState) -> list[DegradedReason]:
    """Return the subset of degraded reasons that can be recovered by retrying."""
    return [r for r in state.degraded_reasons if r in _RECOVERABLE_REASONS]


def _all_recovered(state: LifecycleState) -> bool:
    """Check whether all recoverable subsystems have been restored."""
    return not any(r in _RECOVERABLE_REASONS for r in state.degraded_reasons)


async def _try_recover_reason(state: LifecycleState, reason: DegradedReason) -> None:
    """Attempt recovery for a single degraded reason. Raises on failure."""
    if reason is DegradedReason.ARTIFACT_STORAGE:
        await _try_recover_artifact_storage()
    elif reason is DegradedReason.SUBSCRIPTION_COORDINATOR:
        await _try_recover_subscriptions(state)
    state.degraded_reasons.remove(reason)
    logger.info("Recovered: %s", reason)


async def _attempt_recovery_pass(state: LifecycleState, delay: float) -> None:
    """Try recovering each degraded subsystem once. Failures are logged, not raised."""
    for reason in _get_recoverable(state):
        if state._shutting_down:
            return
        try:
            await _try_recover_reason(state, reason)
        except Exception:
            logger.debug("Recovery retry failed for %s, will retry in %.0fs", reason, delay)


async def _recovery_loop(state: LifecycleState) -> None:
    """Background task: retry degraded subsystems with exponential backoff.

    Only retries subsystems in _RECOVERABLE_REASONS (artifact_storage,
    subscription_coordinator). Credential-based degradation (missing API keys)
    cannot be recovered without a restart.
    """
    delay = 10.0
    max_delay = 60.0

    await asyncio.sleep(delay)

    while not state._shutting_down and _get_recoverable(state):
        await _attempt_recovery_pass(state, delay)

        if _all_recovered(state):
            logger.info("All recoverable subsystems healthy — recovery loop exiting")
            return

        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)


async def _try_recover_artifact_storage() -> None:
    """Attempt to initialize artifact storage (raises on failure)."""
    from syn_adapters.storage.artifact_storage.factory import get_artifact_storage

    storage = await get_artifact_storage()
    await storage.ensure_ready()
    logger.info("Artifact storage bucket verified (recovered)")


async def _try_recover_subscriptions(state: LifecycleState) -> None:
    """Attempt to start subscription coordinator (raises on failure).

    Unlike _init_subscriptions, does NOT append to degraded_reasons on
    failure — the caller handles retry logic.
    """
    realtime = get_realtime()
    state.workflow_dispatcher = await get_workflow_dispatcher()
    coordinator = get_subscription_coordinator(
        realtime_projection=realtime,
        execution_service=state.workflow_dispatcher,
    )
    await coordinator.start()
    state.subscription_service = coordinator
    logger.info("Subscription coordinator started (recovered)")
