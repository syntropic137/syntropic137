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

    def _mask(val: object) -> str:
        if val is None:
            return ""
        s = str(val)
        if not s:
            return ""
        if show_secrets:
            return s
        return s[:4] + "****" if len(s) > 4 else "****"

    app = {
        "app_name": settings.app_name,
        "app_environment": settings.app_environment.value,
        "debug": settings.debug,
        "log_level": settings.log_level,
        "log_format": settings.log_format,
    }

    database = {
        "esp_event_store_db_url": _mask(settings.esp_event_store_db_url)
        if settings.esp_event_store_db_url
        else "",
        "syn_observability_db_url": _mask(settings.syn_observability_db_url)
        if settings.syn_observability_db_url
        else "",
        "event_store_host": settings.event_store_host,
        "event_store_port": settings.event_store_port,
        "event_store_tenant_id": settings.event_store_tenant_id,
    }

    agents = {
        "anthropic_api_key": _mask(settings.anthropic_api_key)
        if settings.anthropic_api_key
        else "",
        "default_agent_timeout_seconds": settings.default_agent_timeout_seconds,
        "default_max_tokens": settings.default_max_tokens,
    }

    storage = {
        "artifact_storage_type": settings.artifact_storage_type,
        "s3_bucket_name": settings.s3_bucket_name or "",
        "dashboard_host": settings.dashboard_host,
        "dashboard_port": settings.dashboard_port,
    }

    return Ok(ConfigSnapshot(app=app, database=database, agents=agents, storage=storage))


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

    issues: list[ConfigIssue] = []

    # Check agent keys
    if not settings.anthropic_api_key:
        issues.append(
            ConfigIssue(
                level="warning",
                category="agents",
                message="ANTHROPIC_API_KEY not set — Claude provider unavailable",
            )
        )
    # Check database
    if not settings.esp_event_store_db_url:
        issues.append(
            ConfigIssue(
                level="warning",
                category="database",
                message="ESP_EVENT_STORE_DB_URL not set — using in-memory event store",
            )
        )

    # Check environment
    if settings.is_production and settings.debug:
        issues.append(
            ConfigIssue(
                level="error",
                category="app",
                message="DEBUG=true in production environment",
            )
        )

    # Check agent availability
    try:
        from syn_adapters.agents import get_available_agents

        available = get_available_agents()
        if not available:
            issues.append(
                ConfigIssue(
                    level="error",
                    category="agents",
                    message="No agent providers available — at least one API key required",
                )
            )
        else:
            issues.append(
                ConfigIssue(
                    level="info",
                    category="agents",
                    message=f"Available providers: {', '.join(p.value for p in available)}",
                )
            )
    except Exception:
        issues.append(
            ConfigIssue(
                level="warning",
                category="agents",
                message="Could not check agent provider availability",
            )
        )

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
