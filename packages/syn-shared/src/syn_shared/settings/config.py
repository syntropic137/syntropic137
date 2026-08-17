"""Settings configuration using Pydantic BaseSettings.

All environment variables are validated on startup.
Required variables will cause an immediate, clear error if missing.
Each variable has a description explaining its purpose and where to get it.

See ADR-004: Environment Configuration with Pydantic Settings.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from syn_shared.env_constants import ENV_CODEX_AUTH_JSON

if TYPE_CHECKING:
    from syn_shared.settings.dev_tooling import DevToolingSettings
    from syn_shared.settings.github import GitHubAppSettings
    from syn_shared.settings.polling import PollingSettings
    from syn_shared.settings.session_store import SessionStoreSettings
    from syn_shared.settings.storage import StorageSettings
    from syn_shared.settings.workspace import (
        ContainerLoggingSettings,
        GitIdentitySettings,
        WorkspaceSecuritySettings,
        WorkspaceSettings,
    )


class AppEnvironment(StrEnum):
    """Application environment."""

    DEVELOPMENT = "development"
    BETA = "beta"
    STAGING = "staging"
    PRODUCTION = "production"
    SELFHOST = "selfhost"
    TEST = "test"
    OFFLINE = "offline"


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
        default="syntropic137",
        description="Application name for logging and identification",
    )

    app_environment: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        description=(
            "Current environment: development, staging, production, test, offline. "
            "Affects logging verbosity, error handling, and feature flags. "
            "Use 'offline' for local dev without Docker or external services."
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
                "For local dev: postgresql://syn:syn_dev_password@localhost:5432/syn "
                "For Docker: postgresql://syn:syn_dev_password@timescaledb:5432/syn"
            ),
        ),
    ] = None

    syn_observability_db_url: Annotated[
        PostgresDsn | None,
        Field(
            default=None,
            description=(
                "Syn137 Observability database URL for agent metrics and application data. "
                "Format: postgresql://user:password@host:port/database "
                "Used by Dashboard API (Python) for: agent_events, workflows, artifacts, projections. "
                "For local dev: postgresql://syn:syn_dev_password@localhost:5432/syn "
                "For Docker: postgresql://syn:syn_dev_password@timescaledb:5432/syn "
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
        default="syn",
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

    syn_workspace_container_dir: str | None = Field(
        default=None,
        description=(
            "Container path for workspace directories when running dashboard in Docker. "
            "Example: /workspaces (mounted volume inside dashboard container)"
        ),
    )

    syn_workspace_host_dir: str | None = Field(
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
        "esp_event_store_db_url", "syn_observability_db_url", "event_store_url", mode="before"
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
            "Claude Code OAuth token. Takes priority over ANTHROPIC_API_KEY when both are set. "
            "Obtain via: claude setup (Claude Code OAuth flow). "
            "At least one of CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is required "
            "for agent execution."
        ),
    )

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Anthropic API key. Used when CLAUDE_CODE_OAUTH_TOKEN is not set. "
            "Get from: https://console.anthropic.com/settings/keys. "
            "At least one of ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN is required "
            "for agent execution."
        ),
    )

    codex_auth_json: SecretStr | None = Field(
        default=None,
        description=(
            "Full contents of Codex ~/.codex/auth.json for ChatGPT subscription auth. "
            "Injected file-only during setup and never passed through argv or logs."
        ),
    )

    @field_validator("codex_auth_json", mode="after")
    @classmethod
    def _normalise_codex_auth_json(cls, value: SecretStr | None) -> SecretStr | None:
        """Repair paste-mangled codex auth, and reject it if it is not JSON.

        This credential is a ~4KB single-line JSON blob that a human moves by
        hand into a secret store. Editors mangle it in predictable ways, and the
        result is a credential that LOOKS present and then fails deep inside
        workspace provisioning - the worst possible failure shape for a secret.

        Observed in the wild (2026-08-17): pasting into a 1Password text field
        produced CSV quoting - the whole value wrapped in `"` with every inner
        quote doubled (`""auth_mode""`). Also common: surrounding single quotes
        carried over from a `.env` line, and stray whitespace or newlines.

        So: normalise the manglings we can recognise, then VALIDATE. An
        unparseable credential raises here, at settings load, naming the problem
        - rather than surfacing as an opaque codex provisioning failure with no
        indication that the secret is the cause.
        """
        if value is None:
            return None

        raw = value.get_secret_value().strip()
        if not raw:
            return None

        # Surrounding quotes from a .env line or a quoting editor.
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            raw = raw[1:-1]
            # CSV convention doubles inner quotes when it wraps a value.
            if '""' in raw:
                raw = raw.replace('""', '"')

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = (
                f"{ENV_CODEX_AUTH_JSON} is not valid JSON ({exc.msg} at position "
                f"{exc.pos}). It must be the exact contents of ~/.codex/auth.json "
                "on a single line. If it was pasted into a secret store, the "
                "editor may have quote-escaped it; re-copy with "
                "`just codex-auth-clip` and paste into a password/concealed field."
            )
            raise ValueError(msg) from exc

        if not isinstance(parsed, dict):
            msg = f"{ENV_CODEX_AUTH_JSON} must be a JSON object, got {type(parsed).__name__}"
            raise ValueError(msg)

        # Re-serialise compactly so downstream always writes a clean auth.json.
        return SecretStr(json.dumps(parsed, separators=(",", ":")))

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

    setup_phase_timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=3600,
        description=(
            "Timeout for the workspace setup phase in seconds. "
            "The setup phase runs the setup script that configures credentials "
            "and clones repositories before the agent starts. "
            "Increase for workflows with large repositories."
        ),
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
    # REDIS
    # =========================================================================

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description=(
            "Redis connection URL for caching and control signal queues. "
            "Format: redis://[:password]@host:port/db "
            "For Docker: redis://redis:6379/0 "
            "For selfhost: built from secrets in selfhost-entrypoint.sh"
        ),
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
    # STORAGE (S3-compatible for artifacts)
    # =========================================================================

    artifact_storage_type: str = Field(
        default="database",
        description=(
            "Artifact storage backend: 'database' (PostgreSQL), 's3' (S3-compatible). "
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
        description=("S3-compatible endpoint URL. Leave empty for AWS S3."),
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
    def is_offline(self) -> bool:
        """Check if running in offline development mode (no Docker, no external services)."""
        return self.app_environment == AppEnvironment.OFFLINE

    @property
    def uses_in_memory_stores(self) -> bool:
        """True when using in-memory stores (test or offline mode)."""
        return self.is_test or self.is_offline

    @property
    def use_in_memory_storage(self) -> bool:
        """Check if in-memory storage would be used (no database configured).

        In-memory storage is used for test and offline environments.
        For local development, configure SYN_OBSERVABILITY_DB_URL to use Docker PostgreSQL.
        """
        return self.syn_observability_db_url is None and self.uses_in_memory_stores

    # =========================================================================
    # WORKSPACE ISOLATION - See ADR-021
    # =========================================================================

    @property
    def workspace(self) -> WorkspaceSettings:
        """Get workspace isolation settings.

        Returns a WorkspaceSettings instance configured from SYN_WORKSPACE_* env vars.
        All workspaces are isolated by default - this controls HOW, not WHETHER.

        See ADR-021: Isolated Workspace Architecture
        """
        from syn_shared.settings.workspace import WorkspaceSettings

        return WorkspaceSettings()

    @property
    def workspace_security(self) -> WorkspaceSecuritySettings:
        """Get workspace security settings.

        Returns security policies applied to all isolated workspaces.
        Defaults are maximally restrictive (no network, read-only root, resource limits).

        See ADR-021: Isolated Workspace Architecture
        """
        from syn_shared.settings.workspace import WorkspaceSecuritySettings

        return WorkspaceSecuritySettings()

    @property
    def git_identity(self) -> GitIdentitySettings:
        """Get git identity settings for workspace commits.

        Returns git user.name, user.email, and credentials for commits.
        Agents use these to commit code with proper attribution.

        See ADR-021: Isolated Workspace Architecture - Git Identity section.
        """
        from syn_shared.settings.workspace import GitIdentitySettings

        return GitIdentitySettings()

    @property
    def container_logging(self) -> ContainerLoggingSettings:
        """Get container logging settings for observability.

        Returns logging configuration for operations inside containers.
        Logs are ephemeral (tmpfs) with secret redaction enabled.

        See ADR-021: Isolated Workspace Architecture - Container Observability.
        """
        from syn_shared.settings.workspace import ContainerLoggingSettings

        return ContainerLoggingSettings()

    # =========================================================================
    # OBJECT STORAGE - See ADR-012
    # =========================================================================

    @property
    def storage(self) -> StorageSettings:
        """Get object storage settings for artifacts.

        Returns a StorageSettings instance configured from SYN_STORAGE_* env vars.
        Supports local filesystem (development) and MinIO (Docker/selfhost).

        See ADR-012: Artifact Storage
        """
        from syn_shared.settings.storage import StorageSettings

        return StorageSettings()

    # =========================================================================
    # CENTRAL SESSION STORE (SeshMagic capture) - opt-in, default OFF
    # =========================================================================

    @property
    def session_store(self) -> SessionStoreSettings:
        """Get central session-store settings.

        Returns a SessionStoreSettings instance configured from
        SYN_SESSION_STORE_* env vars. Disabled unless SYN_SESSION_STORE_URL is
        set; when disabled, nothing at all is injected into workspace
        containers.
        """
        from syn_shared.settings.session_store import SessionStoreSettings

        return SessionStoreSettings()

    # =========================================================================
    # DEVELOPMENT TOOLING
    # =========================================================================

    @property
    def dev_tooling(self) -> DevToolingSettings:
        """Get development tooling settings.

        Returns a DevToolingSettings instance configured from DEV__* env vars.
        Controls local dev tools like webhook proxies, debug servers, etc.
        """
        from syn_shared.settings.dev_tooling import DevToolingSettings

        return DevToolingSettings()

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
        from syn_shared.settings.github import GitHubAppSettings

        return GitHubAppSettings()

    # =========================================================================
    # POLLING (ISS-386) - GitHub Events API hybrid ingestion
    # =========================================================================

    @property
    def polling(self) -> PollingSettings:
        """Get GitHub Events API polling settings.

        Polling is enabled by default for zero-config onboarding.
        Set ``SYN_POLLING_DISABLED=true`` to opt out.
        """
        from syn_shared.settings.polling import PollingSettings

        return PollingSettings()


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Settings are loaded once on first call and cached.
    Validates all environment variables immediately.

    op:// references in .env or os.environ are transparently resolved via
    the 1Password CLI before pydantic reads them. If `op` is unavailable,
    resolution is silently skipped and pydantic validates as normal.

    Returns:
        Validated Settings instance.

    Raises:
        pydantic.ValidationError: If required env vars are missing or invalid.
            Error message includes which variable failed and why.
    """
    from syn_shared.settings.op_resolver import resolve_op_secrets

    resolve_op_secrets()
    return Settings()


def reset_settings() -> None:
    """Clear settings cache (for testing).

    Call this to force reload settings from environment.
    """
    get_settings.cache_clear()
