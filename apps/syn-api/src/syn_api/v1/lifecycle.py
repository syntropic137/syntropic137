"""Lifecycle operations — startup, shutdown, and health checks.

Centralizes application lifecycle management so the dashboard
can delegate to syn_api instead of importing adapters directly.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

from syn_api._wiring import (
    disconnect,
    ensure_connected,
    get_event_store_instance,
    get_github_settings,
    get_realtime,
    get_subscription_coordinator,
    get_workflow_dispatcher,
)
from syn_api.types import Err, LifecycleError, Ok, Result

if TYPE_CHECKING:
    from typing import Any

    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

# Module-level references for lifecycle management
_subscription_service: Any = None
_workflow_dispatcher: Any = None
_degraded_reasons: list[str] = []


async def startup(
    skip_validation: bool = False,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[dict, LifecycleError]:
    """Initialize the application: connect to event store, start subscriptions.

    Critical failures (event store, DB) abort startup.
    Degraded failures (GitHub, Anthropic, Redis, subscriptions) warn and continue.

    Args:
        skip_validation: Skip credential validation (for test mode).
        auth: Optional authentication context.

    Returns:
        Ok({"mode": "full"|"degraded", ...}) on success,
        Err(LifecycleError) on critical failure.
    """
    global _subscription_service, _workflow_dispatcher, _degraded_reasons
    _degraded_reasons = []

    try:
        from syn_shared.settings import get_settings

        settings = get_settings()

        # Validate credentials (unless skipped or in test/offline mode)
        if not skip_validation and not settings.uses_in_memory_stores:
            validate_credentials()

        # Skip subscription service in test environment
        if settings.is_test:
            return Ok({"mode": "full"})

        # Offline mode: seed demo data and return (no Docker/external services)
        if settings.is_offline:
            await _seed_offline_data()
            return Ok({"mode": "full"})

        # ── CRITICAL: event store + DB — abort if unreachable ──────────
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

        # ── DEGRADED: subscription coordinator ────────────────────────
        try:
            realtime = get_realtime()
            _workflow_dispatcher = await get_workflow_dispatcher()
            _subscription_service = get_subscription_coordinator(
                realtime_projection=realtime,
                execution_service=_workflow_dispatcher,
            )
            await _subscription_service.start()
        except Exception:
            logger.exception("Failed to start subscription coordinator (degraded mode)")
            _degraded_reasons.append("subscription_coordinator")

        # Reconcile orphaned sessions and containers from any previous run
        await _reconcile_orphaned_sessions()
        await _cleanup_orphaned_containers()

        mode = "degraded" if _degraded_reasons else "full"
        return Ok({"mode": mode, "degraded_reasons": _degraded_reasons})
    except Exception as e:
        logger.exception("Unexpected startup failure")
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
    global _subscription_service, _workflow_dispatcher

    try:
        # Shut down dispatcher first to prevent new tasks during teardown
        if _workflow_dispatcher is not None:
            with contextlib.suppress(Exception):
                await _workflow_dispatcher.shutdown()
            _workflow_dispatcher = None

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
        Ok(dict) with health status including mode (full/degraded).
    """
    mode = "degraded" if _degraded_reasons else "full"
    response: dict = {"status": "healthy", "mode": mode}

    if _degraded_reasons:
        response["degraded_reasons"] = _degraded_reasons

    if _subscription_service is not None:
        try:
            response["subscription"] = _subscription_service.get_status()
        except Exception:
            response["subscription"] = {"status": "unknown"}

    return Ok(response)


def validate_credentials(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> None:
    """Validate API keys and GitHub App configuration (degraded, not critical).

    Exports ANTHROPIC_API_KEY to os.environ for agent adapters.
    Missing credentials add to _degraded_reasons but never abort startup.

    Args:
        auth: Optional authentication context.
    """
    global _degraded_reasons
    from syn_shared.settings import get_settings

    settings = get_settings()

    # Export Anthropic API key if available (needed for agent execution, not dashboard)
    api_key = settings.anthropic_api_key
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key.get_secret_value()
    elif not settings.is_test:
        logger.warning(
            "ANTHROPIC_API_KEY not configured — agent execution disabled. "
            "Set it in .env or 1Password to enable workflow runs."
        )
        _degraded_reasons.append("anthropic_api_key")

    # Validate GitHub App (warn-only — dashboard should work without it)
    try:
        github = get_github_settings()
        if not github.is_configured and not settings.is_test:
            logger.warning(
                "GitHub App not configured — webhook triggers disabled. "
                "Run 'just setup --stage configure_github_app' to configure."
            )
            _degraded_reasons.append("github_app")
    except Exception:
        logger.exception("Failed to validate GitHub App configuration")
        _degraded_reasons.append("github_app")


async def _reconcile_orphaned_sessions() -> None:
    """Mark sessions stuck in 'running' as failed on startup.

    Any session still 'running' when the framework starts is orphaned —
    its container was killed and can no longer complete normally.
    """
    try:
        from syn_api._wiring import get_projection_mgr

        manager = get_projection_mgr()
        count = await manager.session_list.reconcile_orphaned()
        if count:
            logger.warning("Reconciled %d orphaned session(s) → marked as failed", count)
        else:
            logger.debug("No orphaned sessions found")
    except Exception:
        logger.exception("Failed to reconcile orphaned sessions (non-fatal)")


async def _cleanup_orphaned_containers() -> None:
    """Stop and remove agent containers left running from a previous framework instance.

    Targets:
    - Sidecar containers: label syn.component=sidecar
    - Workspace containers: name prefix agentic-ws-
    """
    import asyncio

    async def _docker_rm(filter_arg: str, label: str) -> None:
        try:
            # List matching container IDs
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "-q",
                "--filter",
                filter_arg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            ids = stdout.decode().split() if stdout else []
            if not ids:
                return

            logger.warning("Stopping %d orphaned %s container(s): %s", len(ids), label, ids)
            stop_proc = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                *ids,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(stop_proc.wait(), timeout=30)
            logger.info("Removed %d orphaned %s container(s)", len(ids), label)
        except Exception:
            logger.debug("Container cleanup skipped for %s (docker may not be available)", label)

    await _docker_rm("label=syn.component=sidecar", "sidecar")
    await _docker_rm("name=agentic-ws-", "workspace")


async def _seed_offline_data() -> None:
    """Seed demo data for offline development mode.

    Creates workflow templates and trigger presets so the dashboard
    renders meaningful content without any external services.
    """
    from syn_api._wiring import ensure_connected, sync_published_events_to_projections

    await ensure_connected()

    # Seed workflow templates
    from syn_adapters.storage import get_event_publisher, get_workflow_repository
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repository(),
        event_publisher=get_event_publisher(),
    )

    workflows_seeded = 0
    for wf_def in _OFFLINE_WORKFLOW_DEFS:
        try:
            from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
                CreateWorkflowTemplateCommand,
            )

            command = CreateWorkflowTemplateCommand(**wf_def)
            await handler.handle(command)
            workflows_seeded += 1
        except Exception:
            logger.debug("Skipped seeding workflow '%s' (may already exist)", wf_def["name"])

    # Seed trigger presets
    import syn_api.v1.triggers as triggers_api

    triggers_seeded = 0
    for preset_name in ("self-healing", "review-fix"):
        try:
            result = await triggers_api.enable_preset(
                preset_name=preset_name,
                repository="demo/offline-repo",
                installation_id="",
                created_by="offline-seed",
            )
            if isinstance(result, Ok):
                triggers_seeded += 1
        except Exception:
            logger.debug("Skipped seeding trigger preset '%s'", preset_name)

    # Sync events to projections so read models are populated
    await sync_published_events_to_projections()

    logger.info(
        "Offline mode: seeded %d workflows, %d triggers",
        workflows_seeded,
        triggers_seeded,
    )


_OFFLINE_WORKFLOW_DEFS: list[dict] = [
    {
        "aggregate_id": "self-heal-pr",
        "name": "Self-Heal PR",
        "description": "Automatically fix failing CI checks by analyzing logs and applying patches.",
        "workflow_type": "implementation",
        "classification": "standard",
        "repository_url": "https://github.com/demo/offline-repo",
        "phases": [
            {
                "phase_id": "diagnose",
                "name": "diagnose",
                "order": 1,
                "description": "Analyze CI failure logs and identify root cause",
                "prompt_template": "Analyze the following CI failure and identify the root cause:\n{ci_logs}",
            },
            {
                "phase_id": "fix",
                "name": "fix",
                "order": 2,
                "description": "Apply automated fix based on diagnosis",
                "prompt_template": "Apply a fix for the diagnosed issue:\n{diagnosis}",
            },
        ],
    },
    {
        "aggregate_id": "documentation-sync",
        "name": "Documentation Sync",
        "description": "Keep documentation in sync with code changes.",
        "workflow_type": "custom",
        "classification": "simple",
        "repository_url": "https://github.com/demo/offline-repo",
        "phases": [
            {
                "phase_id": "detect",
                "name": "detect",
                "order": 1,
                "description": "Detect documentation that needs updating",
                "prompt_template": "Identify documentation that needs updating based on:\n{changes}",
            },
        ],
    },
]
