"""Infrastructure / deployment settings for self-host and Docker Compose.

These variables live in ``infra/.env`` and control Docker Compose overlays,
resource limits, secrets, and networking.  They are **not** read by the
Pydantic ``Settings`` class (which reads root ``.env``).

The class exists so ``scripts/generate_env_example.py`` can auto-generate
``infra/.env.example`` from typed field definitions — same pattern as the
root settings classes.

Environment Variables:
    See field descriptions below.  All variables are optional with sensible
    defaults for local development.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class InfraSettings(BaseSettings):
    """Infrastructure configuration (infra/.env).

    Controls Docker Compose deployment, resource limits, Cloudflare tunnel,
    and self-host-specific tuning.  Application config (API keys, GitHub
    creds, logging) lives in the root ``.env``.
    """

    model_config = SettingsConfigDict(
        env_file="infra/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # DEPLOYMENT
    # =========================================================================

    container_registry: str = Field(
        default="",
        description=(
            "Container registry for pre-built images (optional). "
            "Leave empty to build locally. Set for CI/CD deployments. "
            "Example: ghcr.io/syntropic137"
        ),
    )

    image_tag: str = Field(
        default="latest",
        description=(
            "Image tag for deployment. "
            "Use 'latest' for dev, specific versions (v1.2.3) for production."
        ),
    )

    # =========================================================================
    # DATABASE (PostgreSQL)
    # =========================================================================

    postgres_password: SecretStr = Field(
        default=SecretStr("syn_dev_password"),
        description=(
            "PostgreSQL password. "
            "LOCAL DEV ONLY - This default value is for development convenience. "
            "For PRODUCTION, you MUST use Docker secrets instead "
            "(file: secrets/db-password.txt). "
            "Generate a secure password with: openssl rand -hex 32"
        ),
    )

    postgres_db: str = Field(
        default="syn",
        description="Database name.",
    )

    postgres_user: str = Field(
        default="syn",
        description="Database user.",
    )

    # =========================================================================
    # CLOUDFLARE TUNNEL (Self-Host Only)
    # =========================================================================

    cloudflare_account_id: str = Field(
        default="",
        description=(
            "Cloudflare account ID. [REQUIRED for self-host] "
            "Find at: Cloudflare Dashboard -> Account Home -> right sidebar."
        ),
    )

    cloudflare_api_token: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Cloudflare API token. [REQUIRED for tunnel setup script] "
            "Permissions needed: Zone:Read, DNS:Edit, Cloudflare Tunnel:Edit. "
            "Create at: https://dash.cloudflare.com/profile/api-tokens"
        ),
    )

    cloudflare_zone_id: str = Field(
        default="",
        description=(
            "Cloudflare Zone ID for your domain. [REQUIRED for self-host] "
            "Find at: Domain overview page -> right sidebar -> API section."
        ),
    )

    syn_domain: str = Field(
        default="",
        description=(
            "Domain for Syn137 access. [REQUIRED for self-host] "
            "Example: syn.yourdomain.com. "
            "API will be available at: api.syn.yourdomain.com"
        ),
    )

    cloudflare_tunnel_name: str = Field(
        default="syn-selfhost",
        description="Tunnel name (created automatically if doesn't exist).",
    )

    cloudflare_tunnel_token: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Tunnel token. [REQUIRED for self-host] "
            "With 1Password: auto-resolved from vault - leave empty. "
            "Without 1Password: paste token here. "
            "Get from Cloudflare Zero Trust Dashboard after creating tunnel: "
            "Networks -> Tunnels -> Create -> Copy token. "
            "Or via CLI: cloudflared tunnel token <tunnel-name>"
        ),
    )

    # =========================================================================
    # 1PASSWORD - Docker Build Arg
    # =========================================================================

    include_op_cli: int = Field(
        default=0,
        description=(
            "Include 1Password CLI in dashboard image (set to 1 to enable). "
            "Note: OP_SERVICE_ACCOUNT_TOKEN and other 1Password config live in root .env."
        ),
    )

    # =========================================================================
    # MINIO (Object Storage)
    # =========================================================================

    minio_root_user: str = Field(
        default="minioadmin",
        description="MinIO root credentials (change for production!).",
    )

    minio_root_password: SecretStr = Field(
        default=SecretStr("minioadmin"),
        description="MinIO root password (change for production!).",
    )

    # =========================================================================
    # REDIS
    # =========================================================================

    redis_password: SecretStr = Field(
        default=SecretStr("changeme"),
        description=(
            "Redis password for selfhost deployments. "
            "Also stored as Docker secret: infra/docker/secrets/redis-password.txt. "
            "Generate with: openssl rand -hex 32"
        ),
    )

    # =========================================================================
    # RESOURCE LIMITS
    # =========================================================================

    api_memory_limit: str = Field(default="512m", description="API memory limit.")
    api_cpu_limit: str = Field(default="0.5", description="API CPU limit.")

    ui_memory_limit: str = Field(default="256m", description="UI (nginx) memory limit.")
    ui_cpu_limit: str = Field(default="0.25", description="UI (nginx) CPU limit.")

    postgres_memory_limit: str = Field(default="1g", description="PostgreSQL memory limit.")
    postgres_cpu_limit: str = Field(default="1.0", description="PostgreSQL CPU limit.")

    event_store_memory_limit: str = Field(default="512m", description="Event Store memory limit.")

    collector_memory_limit: str = Field(default="256m", description="Collector memory limit.")
    collector_cpu_limit: str = Field(default="0.25", description="Collector CPU limit.")

    minio_memory_limit: str = Field(default="256m", description="MinIO memory limit.")
    minio_cpu_limit: str = Field(default="0.25", description="MinIO CPU limit.")

    redis_memory_limit: str = Field(default="256m", description="Redis memory limit.")
    redis_cpu_limit: str = Field(default="0.25", description="Redis CPU limit.")

    # =========================================================================
    # SELF-HOST-SPECIFIC (Optional)
    # =========================================================================

    syn_gateway_port: int = Field(
        default=8008,
        description=(
            "Gateway port (nginx reverse proxy). "
            "Default 8008 - change to avoid conflicts."
        ),
    )

    syn_api_password: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Basic auth for UI and API (recommended when using Cloudflare Tunnel). "
            "Webhooks are exempt (use HMAC signature verification). "
            "Omit or leave empty to disable auth (local-only access). "
            "Generate a password with: openssl rand -hex 16"
        ),
    )

    syn_api_user: str = Field(
        default="admin",
        description="Basic auth username for UI and API.",
    )

    restart_policy: str = Field(
        default="always",
        description="Enable automatic container restarts.",
    )

    pg_shared_buffers: str = Field(
        default="256MB",
        description="PostgreSQL tuning: shared_buffers (25% of RAM recommended).",
    )

    pg_work_mem: str = Field(
        default="16MB",
        description="PostgreSQL tuning: work_mem.",
    )

    es_batch_size: int = Field(
        default=100,
        description="Event Store batching size.",
    )

    backup_schedule: str = Field(
        default="0 3 * * *",
        description="Backup cron schedule.",
    )

    backup_retention_days: int = Field(
        default=7,
        description="Number of days to retain backups.",
    )

    backup_dir: str = Field(
        default="/var/backups/syn",
        description="Directory for database backups.",
    )
