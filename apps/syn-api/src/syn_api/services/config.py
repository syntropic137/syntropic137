"""Configuration operations — inspect and validate application config.

Maps to syn_shared.settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api.types import (
    ConfigError,
    ConfigIssue,
    ConfigSnapshot,
    Err,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

_ENV_TEMPLATE = """\
# =============================================================================
# Syntropic137 — Environment Configuration Template
# =============================================================================

# Application
APP_ENVIRONMENT=development          # development | staging | production | test
DEBUG=false

# Event Store (gRPC)
EVENT_STORE_HOST=localhost
EVENT_STORE_PORT=50051
EVENT_STORE_TENANT_ID=syn

# Database
ESP_EVENT_STORE_DB_URL=              # PostgreSQL connection string
SYN_OBSERVABILITY_DB_URL=           # Observability database URL

# Agent API Keys
ANTHROPIC_API_KEY=                   # Required for Claude provider

# Workspace
SYN_WORKSPACE_CONTAINER_DIR=        # Container workspace directory
SYN_WORKSPACE_HOST_DIR=             # Host workspace directory

# Artifact Storage
ARTIFACT_STORAGE_TYPE=database       # database | s3
S3_BUCKET_NAME=
S3_ENDPOINT_URL=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=

# Dashboard
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
"""


def _mask_secret(val: object, *, show: bool) -> str:
    """Mask a secret value, showing only the first 4 characters."""
    if val is None:
        return ""
    s = str(val)
    if not s:
        return ""
    if show:
        return s
    return s[:4] + "****" if len(s) > 4 else "****"


def _mask_optional(val: object, *, show: bool) -> str:
    """Mask an optional secret — return empty string when unset."""
    if not val:
        return ""
    return _mask_secret(val, show=show)


def _build_app_section(settings: object) -> dict[str, object]:
    """Build the 'app' config section."""
    return {
        "app_name": settings.app_name,  # type: ignore[attr-defined]
        "app_environment": settings.app_environment.value,  # type: ignore[attr-defined]
        "debug": settings.debug,  # type: ignore[attr-defined]
        "log_level": settings.log_level,  # type: ignore[attr-defined]
        "log_format": settings.log_format,  # type: ignore[attr-defined]
    }


def _build_database_section(settings: object, *, show_secrets: bool) -> dict[str, object]:
    """Build the 'database' config section."""
    return {
        "esp_event_store_db_url": _mask_optional(
            settings.esp_event_store_db_url, show=show_secrets  # type: ignore[attr-defined]
        ),
        "syn_observability_db_url": _mask_optional(
            settings.syn_observability_db_url, show=show_secrets  # type: ignore[attr-defined]
        ),
        "event_store_host": settings.event_store_host,  # type: ignore[attr-defined]
        "event_store_port": settings.event_store_port,  # type: ignore[attr-defined]
        "event_store_tenant_id": settings.event_store_tenant_id,  # type: ignore[attr-defined]
    }


def _build_agents_section(settings: object, *, show_secrets: bool) -> dict[str, object]:
    """Build the 'agents' config section."""
    return {
        "anthropic_api_key": _mask_optional(
            settings.anthropic_api_key, show=show_secrets  # type: ignore[attr-defined]
        ),
        "default_agent_timeout_seconds": settings.default_agent_timeout_seconds,  # type: ignore[attr-defined]
        "default_max_tokens": settings.default_max_tokens,  # type: ignore[attr-defined]
    }


def _build_storage_section(settings: object) -> dict[str, object]:
    """Build the 'storage' config section."""
    return {
        "artifact_storage_type": settings.artifact_storage_type,  # type: ignore[attr-defined]
        "s3_bucket_name": settings.s3_bucket_name or "",  # type: ignore[attr-defined]
        "dashboard_host": settings.dashboard_host,  # type: ignore[attr-defined]
        "dashboard_port": settings.dashboard_port,  # type: ignore[attr-defined]
    }


async def get_config(
    show_secrets: bool = False,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ConfigSnapshot, ConfigError]:
    """Get the current application configuration.

    Args:
        show_secrets: If True, show secret values. Otherwise mask them.
        auth: Optional authentication context.

    Returns:
        Ok(ConfigSnapshot) on success, Err(ConfigError) on failure.
    """
    try:
        from syn_shared.settings import get_settings

        settings = get_settings()
    except Exception as e:
        return Err(ConfigError.LOAD_FAILED, message=str(e))

    return Ok(
        ConfigSnapshot(
            app=_build_app_section(settings),
            database=_build_database_section(settings, show_secrets=show_secrets),
            agents=_build_agents_section(settings, show_secrets=show_secrets),
            storage=_build_storage_section(settings),
        )
    )


def _validate_agent_keys(settings: object) -> list[ConfigIssue]:
    """Check agent API key configuration."""
    if not settings.anthropic_api_key:  # type: ignore[attr-defined]
        return [
            ConfigIssue(
                level="warning",
                category="agents",
                message="ANTHROPIC_API_KEY not set — Claude provider unavailable",
            )
        ]
    return []


def _validate_database(settings: object) -> list[ConfigIssue]:
    """Check database configuration."""
    if not settings.esp_event_store_db_url:  # type: ignore[attr-defined]
        return [
            ConfigIssue(
                level="warning",
                category="database",
                message="ESP_EVENT_STORE_DB_URL not set — using in-memory event store",
            )
        ]
    return []


def _validate_environment(settings: object) -> list[ConfigIssue]:
    """Check environment-specific constraints."""
    if settings.is_production and settings.debug:  # type: ignore[attr-defined]
        return [
            ConfigIssue(
                level="error",
                category="app",
                message="DEBUG=true in production environment",
            )
        ]
    return []


def _validate_agent_availability() -> list[ConfigIssue]:
    """Check which agent providers are available."""
    try:
        from syn_adapters.agents import get_available_agents

        available = get_available_agents()
    except Exception:
        return [
            ConfigIssue(
                level="warning",
                category="agents",
                message="Could not check agent provider availability",
            )
        ]

    if not available:
        return [
            ConfigIssue(
                level="error",
                category="agents",
                message="No agent providers available — at least one API key required",
            )
        ]
    return [
        ConfigIssue(
            level="info",
            category="agents",
            message=f"Available providers: {', '.join(p.value for p in available)}",
        )
    ]


async def validate_config(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ConfigIssue], ConfigError]:
    """Validate the current configuration and report issues.

    Checks settings validity and agent provider availability.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(list[ConfigIssue]) on success, Err(ConfigError) on failure.
    """
    try:
        from syn_shared.settings import get_settings

        settings = get_settings()
    except Exception as e:
        return Err(ConfigError.LOAD_FAILED, message=str(e))

    issues: list[ConfigIssue] = [
        *_validate_agent_keys(settings),
        *_validate_database(settings),
        *_validate_environment(settings),
        *_validate_agent_availability(),
    ]

    return Ok(issues)


async def get_env_template(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, ConfigError]:
    """Get the .env template for configuring Syntropic137.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(template_string) on success, Err(ConfigError) on failure.
    """
    return Ok(_ENV_TEMPLATE)
