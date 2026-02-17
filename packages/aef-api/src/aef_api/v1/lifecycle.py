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

        # Validate credentials (unless skipped or in test/offline mode)
        if not skip_validation and not settings.uses_in_memory_stores:
            result = validate_credentials()
            if isinstance(result, Err):
                return result

        # Skip subscription service in test environment
        if settings.is_test:
            return Ok(None)

        # Offline mode: seed demo data and return (no Docker/external services)
        if settings.is_offline:
            await _seed_offline_data()
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


async def _seed_offline_data() -> None:
    """Seed demo data for offline development mode.

    Creates workflow templates and trigger presets so the dashboard
    renders meaningful content without any external services.
    """
    from aef_api._wiring import ensure_connected, sync_published_events_to_projections

    await ensure_connected()

    # Seed workflow templates
    from aef_adapters.storage import get_event_publisher, get_workflow_repository
    from aef_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repository(),
        event_publisher=get_event_publisher(),
    )

    workflows_seeded = 0
    for wf_def in _OFFLINE_WORKFLOW_DEFS:
        try:
            from aef_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
                CreateWorkflowTemplateCommand,
            )

            command = CreateWorkflowTemplateCommand(**wf_def)
            await handler.handle(command)
            workflows_seeded += 1
        except Exception:
            logger.debug("Skipped seeding workflow '%s' (may already exist)", wf_def["name"])

    # Seed trigger presets
    import aef_api.v1.triggers as triggers_api

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
        "name": "self-healing-ci",
        "description": "Automatically fix failing CI checks by analyzing logs and applying patches.",
        "phases": [
            {
                "name": "diagnose",
                "description": "Analyze CI failure logs and identify root cause",
                "agent_provider": "claude",
                "prompt_template": "Analyze the following CI failure and identify the root cause:\n{ci_logs}",
            },
            {
                "name": "fix",
                "description": "Apply automated fix based on diagnosis",
                "agent_provider": "claude",
                "prompt_template": "Apply a fix for the diagnosed issue:\n{diagnosis}",
            },
        ],
    },
    {
        "name": "code-review-fix",
        "description": "Address code review feedback by analyzing comments and applying changes.",
        "phases": [
            {
                "name": "analyze",
                "description": "Parse review comments and plan changes",
                "agent_provider": "claude",
                "prompt_template": "Analyze the following code review comments and plan fixes:\n{review_comments}",
            },
            {
                "name": "apply",
                "description": "Apply the planned changes",
                "agent_provider": "claude",
                "prompt_template": "Apply the following planned changes:\n{plan}",
            },
        ],
    },
    {
        "name": "documentation-sync",
        "description": "Keep documentation in sync with code changes.",
        "phases": [
            {
                "name": "detect",
                "description": "Detect documentation that needs updating",
                "agent_provider": "claude",
                "prompt_template": "Identify documentation that needs updating based on:\n{changes}",
            },
        ],
    },
]
