# Environment Configuration

This document describes all environment variables used by Syntropic137.

## Quick Start

1. Generate `.env.example`: `just gen-env`
2. Copy to `.env`: `cp .env.example .env`
3. Fill in required values
4. Run `syn` commands - settings are validated on startup

## Generating .env.example

The `.env.example` file is **auto-generated** from the `Settings` class:

```bash
just gen-env
```

This ensures the example file always matches the actual settings defined in code.
Never edit `.env.example` manually - update `packages/syn-shared/src/syn_shared/settings/config.py` instead.

## Startup Modes

The dashboard supports two startup modes:

| Mode | Meaning | When |
|------|---------|------|
| **full** | All services connected | Event store, DB, subscriptions, GitHub App, Anthropic all available |
| **degraded** | Core infra up, optional services missing | GitHub App not configured, Anthropic key missing, or subscription coordinator failed |

**Critical failures** (event store unreachable, DB connection failed) **abort startup entirely** — the dashboard refuses to serve traffic.

**Degraded services** (no GitHub App, no Anthropic key, no Redis) log warnings but the dashboard starts and reports `"mode": "degraded"` in the `/health` endpoint.

## Environment Variables

All env vars are routed through Pydantic Settings — **never use `os.environ.get()` directly in application code**.

### Application

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_ENVIRONMENT` | No | `development` | Environment: `development`, `beta`, `staging`, `production`, `test`, `offline` |
| `DEBUG` | No | `false` | Enable debug mode (never in production) |

### Database (TimescaleDB — ADR-030)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ESP_EVENT_STORE_DB_URL` | Production | None | Event Sourcing Platform DB URL (domain events) |
| `SYN_OBSERVABILITY_DB_URL` | Production | None | Observability DB URL (agent events, projections) |
| `DATABASE_POOL_SIZE` | No | `5` | Connection pool size |
| `DATABASE_POOL_OVERFLOW` | No | `10` | Max overflow connections |

> **Note:** After ADR-030, both URLs point to the same TimescaleDB instance but are named explicitly for each concern.

### Event Store (gRPC)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EVENT_STORE_HOST` | Production | `localhost` | gRPC event store host (Docker: `event-store`) |
| `EVENT_STORE_PORT` | No | `50051` | gRPC event store port |
| `EVENT_STORE_TENANT_ID` | No | `syn` | Multi-tenant event store tenant ID |
| `EVENT_STORE_TIMEOUT_SECONDS` | No | `30` | Timeout for gRPC calls |

### Redis

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis URL for caching and control signal queues. In selfhost, built from secrets by `selfhost-entrypoint.sh` |

### Logging

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | No | `INFO` | Level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT` | No | `json` | Format: `json` (production), `console` (development) |

### Agent Configuration

| Variable | Required | Default | Description | Where to Get |
|----------|----------|---------|-------------|--------------|
| `ANTHROPIC_API_KEY` | For Claude | None | Anthropic API key | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| `OPENAI_API_KEY` | For OpenAI | None | OpenAI API key | [platform.openai.com](https://platform.openai.com/api-keys) |
| `DEFAULT_AGENT_TIMEOUT_SECONDS` | No | `300` | Default timeout for agent ops |
| `DEFAULT_MAX_TOKENS` | No | `4096` | Default max tokens |

### Object Storage (MinIO — ADR-012)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYN_STORAGE_PROVIDER` | Selfhost | `local` | Provider: `local`, `minio`. **Must be `minio` for Docker/selfhost.** |
| `SYN_STORAGE_MINIO_ENDPOINT` | For MinIO | `` | MinIO endpoint (`host:port`) |
| `SYN_STORAGE_MINIO_ACCESS_KEY` | For MinIO | `` | MinIO access key |
| `SYN_STORAGE_MINIO_SECRET_KEY` | For MinIO | `` | MinIO secret key |
| `SYN_STORAGE_MINIO_SECURE` | No | `false` | Use HTTPS for MinIO (default: `false` for Docker-internal networking) |
| `SYN_STORAGE_BUCKET_NAME` | No | `syn-artifacts` | Bucket name for artifacts |

> **Warning:** `SYN_STORAGE_PROVIDER=local` in non-test environments logs a warning. Set `SYN_STORAGE_PROVIDER=minio` for Docker deployments.

### Proxy Configuration (ISS-43)

Agent containers route API traffic through a shared Envoy proxy for credential injection. Agents never see real API keys — they hold a `proxy-managed` placeholder and send requests to the proxy, which injects credentials via ext_authz.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYN_PROXY_URL` | No | `http://envoy-proxy:8081` | URL of the shared credential injection proxy. Agents use this as `ANTHROPIC_BASE_URL`. |
| `SYN_AGENT_NETWORK` | Selfhost | `syntropic137_selfhost_agent-net` | Docker network agents attach to. Must match the compose project's `agent-net` network name. |

> **Note:** The proxy hostname `envoy-proxy` is the Docker Compose **service name**, not a container name. Docker DNS resolves service names within a compose network. Both the dev and selfhost stacks use the same service name, so this default works everywhere.

### GitHub App (Secure Agent Commits)

For secure, auto-rotating tokens with clear audit trails. See [GitHub App Setup Guide](deployment/github-app-setup.md).

| Variable | Required | Default | Description | Where to Get |
|----------|----------|---------|-------------|--------------|
| `SYN_GITHUB_APP_ID` | For GitHub App | None | GitHub App ID | [github.com/settings/apps](https://github.com/settings/apps) |
| `SYN_GITHUB_APP_NAME` | No | `syn-app` | App name for commit attribution (shows as `<name>[bot]`) | Your app's slug |
| `SYN_GITHUB_PRIVATE_KEY` | For GitHub App | None | `file:` path, raw PEM, or base64 | Download `.pem` from app settings |
| `SYN_GITHUB_WEBHOOK_SECRET` | For webhooks | None | Webhook signature secret | Set during app creation |

> **Note:** If either of `SYN_GITHUB_APP_ID` or `SYN_GITHUB_PRIVATE_KEY` is set, both are required. Installation IDs are resolved dynamically via `get_installation_for_repo()`.

### Webhook Delivery (Development)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEV__SMEE_URL` | No | None | Smee.io webhook proxy URL for local development. Auto-created by `just onboard-dev`. |
| `SYN_DOMAIN` | No | None | Domain for Cloudflare tunnel. Set via `just onboard-dev --tunnel`. Lives in `infra/.env`. |

> **Note:** These are mutually exclusive. If `SYN_DOMAIN` is set, the dev stack uses the Cloudflare tunnel for webhook delivery and ignores `DEV__SMEE_URL`. If neither is set, GitHub webhooks won't reach your local stack — `just onboard-dev` configures one automatically.

### 1Password Integration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| *(vault)* | — | — | Vault name is auto-derived from `APP_ENVIRONMENT` (e.g. `development` -> `syn137-dev`). No manual override needed. |
| `OP_SERVICE_ACCOUNT_TOKEN` | For 1Password | None | Service account token for headless secret resolution |

## Example .env File

```bash
# Application
APP_ENVIRONMENT=development
DEBUG=false

# Database (TimescaleDB — ADR-030)
SYN_OBSERVABILITY_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn

# Event Store
EVENT_STORE_HOST=localhost
EVENT_STORE_PORT=50051

# Redis
REDIS_URL=redis://localhost:6379/0

# Logging
LOG_LEVEL=DEBUG
LOG_FORMAT=console

# Agents
ANTHROPIC_API_KEY=sk-ant-xxx

# Object Storage (use minio for Docker, local for pure dev)
SYN_STORAGE_PROVIDER=local

# GitHub App (optional - for secure agent commits)
# SYN_GITHUB_APP_ID=123456
# SYN_GITHUB_APP_NAME=syn-app
# SYN_GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

## Usage in Code

All environment variables are routed through Pydantic Settings — **never use `os.environ.get()` directly**.

```python
from syn_shared.settings import get_settings

# Settings are validated on first access
settings = get_settings()

# Access settings
if settings.is_development:
    print("Running in dev mode")

# Database
if settings.syn_observability_db_url:
    db_url = str(settings.syn_observability_db_url)

# Redis
redis_url = settings.redis_url  # Always available (has default)

# Secrets are protected
if settings.anthropic_api_key:
    api_key = settings.anthropic_api_key.get_secret_value()

# Storage
storage = settings.storage
if storage.is_minio:
    endpoint = storage.minio_endpoint

# GitHub App
if settings.github.is_configured:
    print(f"Commits will show as: {settings.github.bot_name}")
```

## Validation

Settings are validated immediately when accessed. If a required variable is missing or invalid, you'll get a clear error:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
syn_observability_db_url
  Field required [type=missing, input_value={}, input_type=dict]
```

The dashboard also performs startup validation:
- **Critical failures** (DB/event store unreachable) — startup aborted, no traffic served
- **Degraded services** (GitHub/Anthropic/Redis missing) — warning logged, dashboard starts in degraded mode
