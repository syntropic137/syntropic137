"""Settings configuration using Pydantic BaseSettings.

All environment variables are validated on startup.
Required variables will cause an immediate, clear error if missing.
Each variable has a description explaining its purpose and where to get it.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from aef_shared.settings.github import GitHubAppSettings
    from aef_shared.settings.storage import StorageSettings
    from aef_shared.settings.workspace import (
        ContainerLoggingSettings,
        GitIdentitySettings,
        WorkspaceSecuritySettings,
        WorkspaceSettings,
    )


class AppEnvironment(str, Enum):
    """Application environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """Application settings with validation and documentation.

    All settings are loaded from environment variables.
    Use a .env file for local development.

    Required variables will fail fast on startup with clear error messages.
    Optional variables have sensible defaults for development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars
    )

    # =========================================================================
    # APPLICATION
    # =========================================================================

    app_name: str = Field(
        default="agentic-engineering-framework",
        description="Application name for logging and identification",
    )

    app_environment: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        description=(
            "Current environment: development, staging, production, test. "
            "Affects logging verbosity, error handling, and feature flags."
        ),
    )

    debug: bool = Field(
        default=False,
        description=(
            "Enable debug mode. Shows detailed errors and enables debug logging. "
            "Never enable in production."
        ),
    )

    # =========================================================================
    # DATABASE CONNECTIONS (ADR-030: Unified TimescaleDB)
    # =========================================================================
    # After ADR-030, we use a single TimescaleDB instance with explicit URLs
    # for each concern. Both point to the same database but named explicitly.

    esp_event_store_db_url: Annotated[
        PostgresDsn | None,
        Field(
            default=None,
            description=(
                "Event Sourcing Platform database URL for domain events. "
                "Format: postgresql://user:password@host:port/database "
                "Used by Event Store (Rust) for event sourcing tables: events, aggregates, etc. "
                "For local dev: postgresql://aef:aef_dev_password@localhost:5432/aef "
                "For Docker: postgresql://aef:aef_dev_password@timescaledb:5432/aef"
            ),
        ),
    ] = None

    aef_observability_db_url: Annotated[
        PostgresDsn | None,
        Field(
            default=None,
            description=(
                "AEF Observability database URL for agent metrics and application data. "
                "Format: postgresql://user:password@host:port/database "
                "Used by Dashboard API (Python) for: agent_events, workflows, artifacts, projections. "
                "For local dev: postgresql://aef:aef_dev_password@localhost:5432/aef "
                "For Docker: postgresql://aef:aef_dev_password@timescaledb:5432/aef "
                "NOTE: Points to SAME database as ESP after ADR-030 consolidation."
            ),
        ),
    ] = None

    database_pool_size: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Database connection pool size. Increase for high-traffic production.",
    )

    database_pool_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Max overflow connections beyond pool_size for burst traffic.",
    )

    # =========================================================================
    # EVENT STORE (gRPC) - See ADR-007: Event Store Integration
    # =========================================================================

    event_store_host: str = Field(
        default="localhost",
        description=(
            "Event Store Server gRPC host. "
            "For Docker: event-store (service name). "
            "For local dev: localhost"
        ),
    )

    event_store_port: int = Field(
        default=50051,
        ge=1024,
        le=65535,
        description="Event Store Server gRPC port.",
    )

    event_store_tenant_id: str = Field(
        default="aef",
        description=(
            "Tenant ID for multi-tenant Event Store Server. Each tenant has isolated event streams."
        ),
    )

    event_store_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout for Event Store gRPC calls in seconds.",
    )

    event_store_url: str | None = Field(
        default=None,
        description=(
            "DEPRECATED: Use event_store_host and event_store_port instead. "
            "Legacy gRPC URL for the event store service."
        ),
    )

    # =========================================================================
    # WORKSPACE SETTINGS - Docker-in-Docker Deployment
    # =========================================================================

    aef_workspace_container_dir: str | None = Field(
        default=None,
        description=(
            "Container path for workspace directories when running dashboard in Docker. "
            "Example: /workspaces (mounted volume inside dashboard container)"
        ),
    )

    aef_workspace_host_dir: str | None = Field(
        default=None,
        description=(
            "Host path for Docker daemon volume mounts. Required when dashboard runs in Docker. "
            "Example: /Users/user/repo/workspaces or ${PWD}/workspaces"
        ),
    )

    # =========================================================================
    # VALIDATORS - Convert empty strings to None
    # =========================================================================

    @field_validator(
        "esp_event_store_db_url", "aef_observability_db_url", "event_store_url", mode="before"
    )
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        """Convert empty strings to None for optional URL fields."""
        if v == "":
            return None
        return v

    # =========================================================================
    # LOGGING
    # =========================================================================

    log_level: str = Field(
        default="INFO",
        description=(
            "Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL. "
            "Use DEBUG for development, INFO for production."
        ),
    )

    log_format: str = Field(
        default="json",
        description=(
            "Log output format: 'json' for structured logs (production), "
            "'console' for human-readable (development)."
        ),
    )

    # =========================================================================
    # AGENT CONFIGURATION
    # =========================================================================

    claude_code_oauth_token: SecretStr | None = Field(
        default=None,
        description=(
            "Claude Code OAuth token for Claude models. "
            "Obtained via Claude Code OAuth flow. "
            "If set, takes priority over ANTHROPIC_API_KEY."
        ),
    )

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Anthropic API key for Claude models. "
            "Get from: https://console.anthropic.com/settings/keys "
            "Required when using Claude agent adapter (unless CLAUDE_CODE_OAUTH_TOKEN is set)."
        ),
    )

    openai_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "OpenAI API key for GPT models. "
            "Get from: https://platform.openai.com/api-keys "
            "Required when using OpenAI agent adapter."
        ),
    )

    default_agent_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Default timeout for agent operations in seconds.",
    )

    default_max_tokens: int = Field(
        default=4096,
        ge=100,
        le=200000,
        description="Default max tokens for agent responses.",
    )

    # =========================================================================
    # COLLECTOR (Observability) - See ADR-017, ADR-018
    # =========================================================================

    collector_url: str | None = Field(
        default=None,
        description=(
            "URL for the Collector service (Pattern 2: Event Log + CQRS). "
            "Format: http://host:port "
            "For local dev: http://localhost:8080 "
            "For Docker: http://collector:8080 "
            "When not set, tool events are not sent to collector."
        ),
    )

    collector_api_key: SecretStr | None = Field(
        default=None,
        description="API key for Collector service authentication (optional).",
    )

    # =========================================================================
    # HOOKS (Observability) - Legacy
    # =========================================================================

    hook_backend_url: str | None = Field(
        default=None,
        description=(
            "URL for hook backend service for observability events. "
            "Format: http://host:port "
            "For local dev: http://localhost:8080 "
            "When not set, uses JSONL file backend at .agentic/hooks/events.jsonl"
        ),
    )

    hook_batch_size: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Number of events to batch before sending to hook backend.",
    )

    hook_flush_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Max seconds to wait before flushing buffered hook events.",
    )

    # =========================================================================
    # DASHBOARD
    # =========================================================================

    dashboard_port: int = Field(
        default=8000,
        ge=1024,
        le=65535,
        description="Port for the dashboard API server.",
    )

    dashboard_host: str = Field(
        default="127.0.0.1",
        description="Host to bind the dashboard API server.",
    )

    # =========================================================================
    # STORAGE (S3/Supabase for artifacts)
    # =========================================================================

    artifact_storage_type: str = Field(
        default="database",
        description=(
            "Artifact storage backend: 'database' (PostgreSQL), 's3' (S3/Supabase). "
            "Start with database, migrate to s3 for large artifacts."
        ),
    )

    s3_bucket_name: str | None = Field(
        default=None,
        description=(
            "S3 bucket name for artifact storage. Required when artifact_storage_type is 's3'."
        ),
    )

    s3_endpoint_url: str | None = Field(
        default=None,
        description=(
            "S3-compatible endpoint URL. "
            "For Supabase: https://<project>.supabase.co/storage/v1/s3 "
            "Leave empty for AWS S3."
        ),
    )

    s3_access_key_id: SecretStr | None = Field(
        default=None,
        description="S3 access key ID. Required when using S3 storage.",
    )

    s3_secret_access_key: SecretStr | None = Field(
        default=None,
        description="S3 secret access key. Required when using S3 storage.",
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_environment == AppEnvironment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_environment == AppEnvironment.PRODUCTION

    @property
    def is_test(self) -> bool:
        """Check if running in test mode."""
        return self.app_environment == AppEnvironment.TEST

    @property
    def use_in_memory_storage(self) -> bool:
        """Check if in-memory storage would be used (no database configured).

        WARNING: In-memory storage is for TESTING ONLY.
        For local development, configure AEF_OBSERVABILITY_DB_URL to use Docker PostgreSQL.
        """
        return self.aef_observability_db_url is None and self.is_test

    # =========================================================================
    # WORKSPACE ISOLATION - See ADR-021
    # =========================================================================

    @property
    def workspace(self) -> WorkspaceSettings:
        """Get workspace isolation settings.

        Returns a WorkspaceSettings instance configured from AEF_WORKSPACE_* env vars.
        All workspaces are isolated by default - this controls HOW, not WHETHER.

        See ADR-021: Isolated Workspace Architecture
        """
        from aef_shared.settings.workspace import WorkspaceSettings

        return WorkspaceSettings()

    @property
    def workspace_security(self) -> WorkspaceSecuritySettings:
        """Get workspace security settings.

        Returns security policies applied to all isolated workspaces.
        Defaults are maximally restrictive (no network, read-only root, resource limits).

        See ADR-021: Isolated Workspace Architecture
        """
        from aef_shared.settings.workspace import WorkspaceSecuritySettings

        return WorkspaceSecuritySettings()

    @property
    def git_identity(self) -> GitIdentitySettings:
        """Get git identity settings for workspace commits.

        Returns git user.name, user.email, and credentials for commits.
        Agents use these to commit code with proper attribution.

        See ADR-021: Isolated Workspace Architecture - Git Identity section.
        """
        from aef_shared.settings.workspace import GitIdentitySettings

        return GitIdentitySettings()

    @property
    def container_logging(self) -> ContainerLoggingSettings:
        """Get container logging settings for observability.

        Returns logging configuration for operations inside containers.
        Logs are ephemeral (tmpfs) with secret redaction enabled.

        See ADR-021: Isolated Workspace Architecture - Container Observability.
        """
        from aef_shared.settings.workspace import ContainerLoggingSettings

        return ContainerLoggingSettings()

    # =========================================================================
    # OBJECT STORAGE - See ADR-012
    # =========================================================================

    @property
    def storage(self) -> StorageSettings:
        """Get object storage settings for artifacts.

        Returns a StorageSettings instance configured from AEF_STORAGE_* env vars.
        Supports local filesystem (development) and Supabase (production).

        See ADR-012: Artifact Storage
        """
        from aef_shared.settings.storage import StorageSettings

        return StorageSettings()

    # =========================================================================
    # GITHUB APP - See HANDOFF-GITHUB-APP.md
    # =========================================================================

    @property
    def github(self) -> GitHubAppSettings:
        """Get GitHub App settings for secure authentication.

        Returns GitHub App configuration for auto-rotating tokens.
        Commits from agents show as '<app_name>[bot]'.

        See HANDOFF-GITHUB-APP.md for architecture details.
        """
        from aef_shared.settings.github import GitHubAppSettings

        return GitHubAppSettings()


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Settings are loaded once on first call and cached.
    Validates all environment variables immediately.

    Returns:
        Validated Settings instance.

    Raises:
        pydantic.ValidationError: If required env vars are missing or invalid.
            Error message includes which variable failed and why.
    """
    return Settings()


def reset_settings() -> None:
    """Clear settings cache (for testing).

    Call this to force reload settings from environment.
    """
    get_settings.cache_clear()
