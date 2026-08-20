"""Lifecycle operations — startup, shutdown, and health checks.

Centralizes application lifecycle management so the dashboard
can delegate to syn_api instead of importing adapters directly.

Service registration uses a declarative registry (ADR-057) so that
adding a new degradable service requires exactly one entry in
_SERVICE_REGISTRY — initialization, recovery, and shutdown are all
derived from that single declaration.
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
from syn_shared.settings.session_store import (
    ENV_SYN_SESSION_STORE_AUTH_TOKEN,
    ENV_SYN_SESSION_STORE_URL,
    SessionStoreSettings,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_adapters.conversations.minio import MinioConversationStorage
    from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
    from syn_api._wiring import BackgroundWorkflowDispatcher
    from syn_domain.contexts.github.services import (
        CheckRunIngestionService,
        GitHubEventIngestionScheduler,
    )

logger = logging.getLogger(__name__)


def _handle_recovery_task_exception(task: asyncio.Task[None]) -> None:
    """Log exceptions from the lifecycle recovery background task."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Lifecycle recovery task crashed: %s",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


class DegradedReason(StrEnum):
    """Reasons the API may enter degraded mode.

    StrEnum so values serialize directly to JSON in health responses.
    """

    ARTIFACT_STORAGE = "artifact_storage"
    CLAUDE_PLUGIN_STORAGE = "claude_plugin_storage"
    SKILL_STORAGE = "skill_storage"
    CONVERSATION_STORAGE = "conversation_storage"
    SUBSCRIPTION_COORDINATOR = "subscription_coordinator"
    EVENT_POLLER = "event_poller"
    CHECK_RUN_POLLER = "check_run_poller"
    ANTHROPIC_API_KEY = "anthropic_api_key"
    GITHUB_APP = "github_app"


@dataclass
class LifecycleState:
    """Mutable state managed across startup / shutdown / health_check."""

    subscription_service: CoordinatorSubscriptionService | None = None
    workflow_dispatcher: BackgroundWorkflowDispatcher | None = None
    event_poller: GitHubEventIngestionScheduler | None = None
    check_run_poller: CheckRunIngestionService | None = None
    conversation_storage: MinioConversationStorage | None = None
    degraded_reasons: list[DegradedReason] = field(default_factory=list)
    _recovery_task: asyncio.Task[None] | None = None
    _shutting_down: bool = False


# ── Declarative Service Registry (ADR-057) ─────────────────────────
#
# Each degradable service is declared once in _SERVICE_REGISTRY.
# The startup loop, recovery loop, and shutdown sequence all iterate
# this registry — no manual if/elif dispatch or separate frozensets.
#
# To add a new service:
#   1. Add a value to DegradedReason
#   2. Write an _init_<service>(state) function (raises on failure)
#   3. Optionally write a _shutdown_<service>(state) function
#   4. Add a _ServiceEntry to _SERVICE_REGISTRY
#
# That's it. Recovery reuses init_fn, health is derived from state.


@dataclass(frozen=True)
class _ServiceEntry:
    """One lifecycle-managed degradable service (ADR-057)."""

    reason: DegradedReason
    init_fn: Callable[[LifecycleState], Awaitable[None]]
    recoverable: bool = False
    shutdown_fn: Callable[[LifecycleState], Awaitable[None]] | None = None


# Registry is defined after _init_* functions below — see _SERVICE_REGISTRY.


_state = LifecycleState()


# ── Public API ──────────────────────────────────────────────────────


async def _init_degradable_services(state: LifecycleState) -> None:
    """Initialize all degradable services and start recovery if needed (ADR-057).

    Each service in the registry is attempted; failures are logged and the
    service is marked as degraded. A background recovery loop is spawned
    for any recoverable failures.
    """
    for entry in _SERVICE_REGISTRY:
        try:
            await entry.init_fn(state)
        except Exception:
            logger.exception("%s initialization failed (degraded mode)", entry.reason)
            state.degraded_reasons.append(entry.reason)

    await reconcile_orphaned_sessions()
    await cleanup_orphaned_containers()

    # Spawn a background recovery loop for any recoverable degradations.
    recoverable = [r for r in state.degraded_reasons if _is_recoverable(r)]
    if recoverable:
        task = asyncio.create_task(
            _recovery_loop(state),
            name="lifecycle-recovery",
        )
        task.add_done_callback(_handle_recovery_task_exception)
        state._recovery_task = task


async def startup(
    skip_validation: bool = False,
) -> Result[dict, LifecycleError]:
    """Initialize the application: connect to event store, start subscriptions.

    Startup sequence (order matters):
      1. Event store connection (CRITICAL — abort on failure)
      2. Degradable services via _SERVICE_REGISTRY (ADR-057)
      3. Orphan reconciliation (always runs)

    Critical failures (event store, DB) abort startup.
    Degraded failures (GitHub, Anthropic, Redis, subscriptions) warn and continue.

    Args:
        skip_validation: Skip credential validation (for test mode).

    Returns:
        Ok({"mode": "full"|"degraded", ...}) on success,
        Err(LifecycleError) on critical failure.
    """
    _state._shutting_down = False
    _state.degraded_reasons = []

    from syn_shared.settings import get_settings

    settings = get_settings()

    if not skip_validation and not settings.uses_in_memory_stores:
        validate_credentials(_state.degraded_reasons)

    try:
        _log_session_capture_posture(settings.session_store, settings.app_environment)
    except Exception:
        # Diagnostics must never become a startup prerequisite. No exception
        # object and no exc_info: a settings error can echo its input, and the
        # input here may be the write token.
        logger.warning("Could not determine session capture posture at startup.")

    if settings.is_test:
        return Ok({"mode": "full"})

    if settings.is_offline:
        await seed_offline_data()
        return Ok({"mode": "full"})

    # Critical path — abort on failure
    result = await _init_event_store()
    if isinstance(result, Err):
        return result

    # ADR-060: Initialize shared DB pool for durable dedup and cursor store.
    # Best-effort — if it fails, services fall back to Redis/in-memory.
    try:
        from syn_api._wiring_db import init_shared_db_pool

        await init_shared_db_pool()
    except Exception:
        logger.warning("Shared DB pool init failed — dedup will use Redis fallback", exc_info=True)

    await _init_degradable_services(_state)

    mode = "degraded" if _state.degraded_reasons else "full"
    return Ok({"mode": mode, "degraded_reasons": _state.degraded_reasons})


async def shutdown() -> Result[None, LifecycleError]:
    """Gracefully shut down: stop subscriptions, disconnect from event store.

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

        # Shutdown services in reverse registration order (ADR-057).
        for entry in reversed(_SERVICE_REGISTRY):
            if entry.shutdown_fn is not None:
                with contextlib.suppress(Exception):
                    await entry.shutdown_fn(_state)

        # ADR-060: Close shared DB pool
        with contextlib.suppress(Exception):
            from syn_api._wiring_db import close_shared_db_pool

            await close_shared_db_pool()

        await disconnect()
        return Ok(None)
    except Exception as e:
        return Err(LifecycleError.CONNECTION_FAILED, message=str(e))


async def health_check() -> Result[dict, LifecycleError]:
    """Check application health.

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


def _log_session_capture_posture(store: SessionStoreSettings, app_environment: str) -> None:
    """Say once, at startup, how session capture is CONFIGURED.

    Configuration only. Nothing here contacts the store, so this reports what
    was asked for, not what works - a reachable store, a valid token and a
    writable spool are all still unproven at this point. The wording says
    "configured" for that reason; claiming capture is working and being wrong
    would make this line worse than silence.

    Capture is a per-workspace concern, so its posture was previously only
    observable after a workflow ran: the unauthenticated warning fired at
    provisioning, and an operator who never started one saw nothing.

    NO PART OF THE STORE URL IS LOGGED. Not the raw value, and not a
    sanitised scheme/host/port either: every one of those components is
    operator-supplied, so a token pasted into the host, the scheme, or a
    numeric port would land in the record. An invariant with a "unless the
    operator did something odd" clause is not an invariant, and this one has
    to hold absolutely because the alternative is a credential in a log
    aggregator.

    What identifies the destination instead is the DEPLOYMENT, which is
    derived from AppEnvironment and cannot contain a secret, plus the operator's
    own SYN_SESSION_STORE_LABEL when one is declared. The label exists because
    the deployment separates ENVIRONMENTS but not tenants within one: two stores
    differing only by URL path produce an identical posture line without it
    (#849). It is declared non-secret by the operator rather than derived from a
    value that may not be, which is why it can be logged when no part of the URL
    can.
    """
    from syn_adapters.workspace_backends.agentic.session_store_env import (
        deployment_identity,
    )

    if not store.is_enabled:
        logger.info(
            "Session capture is OFF (no %s configured). Workflows run "
            "normally; no transcripts are exported.",
            ENV_SYN_SESSION_STORE_URL,
        )
        return

    deployment = deployment_identity(app_environment)
    label = store.display_label
    destination = f"{deployment} (store: {label})" if label else deployment

    if store.is_unauthenticated:
        logger.warning(
            "Session capture is configured for %s (%s is set) but there is NO "
            "write token (%s). If the store requires authentication this fails "
            "at finalize with 401, AFTER the workspace has run, and the "
            "exporter suppresses the cause to avoid leaking the credential. "
            "Set the token, or ignore this if the store is deliberately open.",
            destination,
            ENV_SYN_SESSION_STORE_URL,
            ENV_SYN_SESSION_STORE_AUTH_TOKEN,
        )
        return

    logger.info(
        "Session capture is configured for %s (%s and a write token are set). "
        "Not yet verified: the next workflow is the first runtime check, so "
        "confirm its capture outcome - only CAPTURED proves the store was "
        "actually reachable and writable.",
        destination,
        ENV_SYN_SESSION_STORE_URL,
    )


async def _init_event_store() -> Result[None, LifecycleError]:
    """Initialize event store and verify connection (critical).

    The event store is the only CRITICAL service — failure aborts startup.
    It is NOT in the service registry because it uses a different error
    contract (returns Result instead of raising).
    """
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


# ── Service init functions ─────────────────────────────────────────
#
# Each function raises on failure (the registry loop catches).
# Recovery reuses the same init_fn — no separate _try_recover_* needed
# unless the recovery path differs from first-time init.


async def _init_artifact_storage(state: LifecycleState) -> None:  # noqa: ARG001
    """Ensure artifact storage bucket exists at startup."""
    from syn_adapters.storage.artifact_storage.factory import get_artifact_storage

    storage = await get_artifact_storage()
    await storage.ensure_ready()
    logger.info("Artifact storage bucket verified")


async def _init_claude_plugin_storage(state: LifecycleState) -> None:  # noqa: ARG001
    """Ensure claude plugin storage bucket exists at startup (issue #726)."""
    from syn_adapters.storage.claude_plugin_storage.factory import get_claude_plugin_storage

    storage = await get_claude_plugin_storage()
    await storage.ensure_ready()
    logger.info("Claude plugin storage bucket verified")


async def _init_skill_storage(state: LifecycleState) -> None:  # noqa: ARG001
    """Ensure skill storage bucket exists at startup (issue #772, ADR-012)."""
    from syn_adapters.storage.skill_storage.factory import get_skill_storage

    storage = await get_skill_storage()
    await storage.ensure_ready()
    logger.info("Skill storage bucket verified")


async def _init_conversation_storage(state: LifecycleState) -> None:
    """Initialize conversation storage (MinIO + PostgreSQL pool).

    On recovery, resets the singleton so a fresh instance is created.
    """
    from syn_adapters.conversations.minio import (
        get_conversation_storage,
        reset_conversation_storage,
    )

    # If retrying after a prior failure, reset so we get a fresh instance.
    if DegradedReason.CONVERSATION_STORAGE in state.degraded_reasons:
        reset_conversation_storage()

    storage = await get_conversation_storage()
    state.conversation_storage = storage
    logger.info("Conversation storage initialized")


async def _shutdown_conversation_storage(state: LifecycleState) -> None:
    """Close conversation storage pool and reset the singleton.

    Resetting the singleton ensures a fresh instance on next startup,
    which matters for tests and lifespan restarts in the same process.
    """
    from syn_adapters.conversations.minio import reset_conversation_storage

    try:
        if state.conversation_storage is not None:
            await state.conversation_storage.close()
    finally:
        state.conversation_storage = None
        reset_conversation_storage()


async def _init_subscriptions(state: LifecycleState) -> None:
    """Start subscription coordinator.

    Reuses the existing workflow dispatcher when present to avoid
    orphaning a running dispatcher on each recovery attempt.
    """
    realtime = get_realtime()
    workflow_dispatcher = state.workflow_dispatcher
    if workflow_dispatcher is None:
        workflow_dispatcher = await get_workflow_dispatcher()
    coordinator = get_subscription_coordinator(
        realtime_projection=realtime,
        execution_service=workflow_dispatcher,
    )
    await coordinator.start()
    # Only assign to state after coordinator starts successfully,
    # so a partial failure doesn't orphan the dispatcher.
    state.workflow_dispatcher = workflow_dispatcher
    state.subscription_service = coordinator
    logger.info("Subscription coordinator started")


async def _shutdown_subscriptions(state: LifecycleState) -> None:
    """Stop subscription coordinator and workflow dispatcher."""
    if state.workflow_dispatcher is not None:
        await state.workflow_dispatcher.shutdown()
        state.workflow_dispatcher = None
    if state.subscription_service is not None:
        await state.subscription_service.stop()
        state.subscription_service = None


async def _init_event_poller(state: LifecycleState) -> None:
    """Start the GitHub Events API poller.

    See ADR-060: Restart-safe trigger deduplication (cold-start fence, cursor persistence).
    """
    from syn_shared.settings import get_settings

    settings = get_settings()

    if not settings.github.is_configured:
        logger.info("GitHub App not configured — event poller disabled")
        return

    if not settings.polling.enabled:
        logger.info("Event polling disabled by configuration")
        return

    from syn_adapters.github.client import get_github_client
    from syn_adapters.github.events_api_client import GitHubEventsAPIClient
    from syn_api._wiring import (
        get_event_pipeline,
        get_trigger_store,
        get_webhook_health_tracker,
    )
    from syn_domain.contexts.github.services import (
        GitHubEventIngestionScheduler,
        GitHubRepoIngestionService,
    )

    # ADR-060: Wire persistent cursor store for restart-safe polling.
    # HistoricalPoller base class uses this for cold-start fence + ETag persistence.
    cursor_store = None
    try:
        from syn_api._wiring_db import get_shared_db_pool

        pool = get_shared_db_pool()
        if pool is not None:
            from syn_adapters.github.poller_cursor_store import PostgresPollerCursorStore

            cursor_store = PostgresPollerCursorStore(pool)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
            logger.info("Poller cursor store initialized (ADR-060)")
    except Exception:
        logger.warning("Cursor store unavailable - poller will re-fetch on restart", exc_info=True)

    if cursor_store is None:
        if not settings.uses_in_memory_stores:
            logger.error(
                "Durable poller cursor store unavailable in production - "
                "disabling event poller to prevent cold-start restart storms (ADR-060)"
            )
            return
        from syn_adapters.github.poller_cursor_store import InMemoryPollerCursorStore

        cursor_store = InMemoryPollerCursorStore()
        logger.warning("Using in-memory cursor store - cold-start fence resets on restart")

    events_client = GitHubEventsAPIClient(get_github_client())
    repo_service = GitHubRepoIngestionService(
        events_api=events_client,
        pipeline=get_event_pipeline(),
        cursor_store=cursor_store,
    )
    poller = GitHubEventIngestionScheduler(
        repo_service=repo_service,
        health_tracker=get_webhook_health_tracker(),
        trigger_store=get_trigger_store(),
        settings=settings.polling,
    )
    await poller.start()
    state.event_poller = poller
    logger.info("GitHub event poller started")


async def _shutdown_event_poller(state: LifecycleState) -> None:
    """Stop the GitHub event poller."""
    if state.event_poller is not None:
        await state.event_poller.stop()
        state.event_poller = None


async def _init_check_run_poller(state: LifecycleState) -> None:
    """Start the check-run poller for poll-based self-healing (#602).

    Polls the GitHub Checks API for CI failures on PR commits. Enables
    self-healing without webhooks — zero-config onboarding.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()

    if not settings.github.is_configured:
        logger.info("GitHub App not configured — check-run poller disabled")
        return

    if not settings.polling.enabled:
        logger.info("Event polling disabled — check-run poller disabled")
        return

    from syn_adapters.github.checks_api_client import GitHubChecksAPIClient
    from syn_adapters.github.client import get_github_client
    from syn_api._wiring import (
        get_event_pipeline,
        get_pending_sha_store,
        get_trigger_store,
        get_webhook_health_tracker,
    )
    from syn_domain.contexts.github.services import CheckRunIngestionService

    poller = CheckRunIngestionService(
        checks_api=GitHubChecksAPIClient(get_github_client()),
        pipeline=get_event_pipeline(),
        sha_store=get_pending_sha_store(),
        health_tracker=get_webhook_health_tracker(),
        trigger_store=get_trigger_store(),
        settings=settings.polling,
    )
    get_event_pipeline().add_observer(poller.on_pr_event)
    await poller.start()
    state.check_run_poller = poller
    logger.info("Check-run poller started")


async def _shutdown_check_run_poller(state: LifecycleState) -> None:
    """Stop the check-run poller."""
    if state.check_run_poller is not None:
        await state.check_run_poller.stop()
        state.check_run_poller = None


# ── Service Registry (ADR-057) ─────────────────────────────────────
#
# Single source of truth for all degradable services. To add a service:
#   1. Add a DegradedReason enum value
#   2. Write an _init_<name>(state) function that raises on failure
#   3. Optionally write a _shutdown_<name>(state) function
#   4. Add a _ServiceEntry here
#
# The startup loop, recovery loop, and shutdown sequence all derive
# their behavior from this registry — no other bookkeeping needed.

_SERVICE_REGISTRY: tuple[_ServiceEntry, ...] = (
    _ServiceEntry(
        reason=DegradedReason.ARTIFACT_STORAGE,
        init_fn=_init_artifact_storage,
        recoverable=True,
    ),
    _ServiceEntry(
        reason=DegradedReason.CLAUDE_PLUGIN_STORAGE,
        init_fn=_init_claude_plugin_storage,
        recoverable=True,
    ),
    _ServiceEntry(
        reason=DegradedReason.SKILL_STORAGE,
        init_fn=_init_skill_storage,
        recoverable=True,
    ),
    _ServiceEntry(
        reason=DegradedReason.CONVERSATION_STORAGE,
        init_fn=_init_conversation_storage,
        recoverable=True,
        shutdown_fn=_shutdown_conversation_storage,
    ),
    _ServiceEntry(
        reason=DegradedReason.SUBSCRIPTION_COORDINATOR,
        init_fn=_init_subscriptions,
        recoverable=True,
        shutdown_fn=_shutdown_subscriptions,
    ),
    _ServiceEntry(
        reason=DegradedReason.EVENT_POLLER,
        init_fn=_init_event_poller,
        recoverable=False,
        shutdown_fn=_shutdown_event_poller,
    ),
    _ServiceEntry(
        reason=DegradedReason.CHECK_RUN_POLLER,
        init_fn=_init_check_run_poller,
        recoverable=False,
        shutdown_fn=_shutdown_check_run_poller,
    ),
)


# ── Recovery helpers (ADR-057) ─────────────────────────────────────


def _is_recoverable(reason: DegradedReason) -> bool:
    """Check if a degraded reason can be recovered by retrying."""
    return any(e.reason == reason and e.recoverable for e in _SERVICE_REGISTRY)


def _get_recoverable(state: LifecycleState) -> list[DegradedReason]:
    """Return the subset of degraded reasons that can be recovered by retrying."""
    return [r for r in state.degraded_reasons if _is_recoverable(r)]


def _all_recovered(state: LifecycleState) -> bool:
    """Check whether all recoverable subsystems have been restored."""
    return not any(_is_recoverable(r) for r in state.degraded_reasons)


async def _try_recover_reason(state: LifecycleState, reason: DegradedReason) -> None:
    """Attempt recovery for a single degraded reason. Raises on failure."""
    entry = next((e for e in _SERVICE_REGISTRY if e.reason == reason), None)
    if entry is None:
        return
    await entry.init_fn(state)
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

    Only retries subsystems marked as recoverable in _SERVICE_REGISTRY.
    Credential-based degradation (missing API keys) cannot be recovered
    without a restart.
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
