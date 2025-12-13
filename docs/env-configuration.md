# Environment Configuration

This document describes all environment variables used by the Agentic Engineering Framework.

## Quick Start

1. Generate `.env.example`: `just gen-env`
2. Copy to `.env`: `cp .env.example .env`
3. Fill in required values
4. Run `aef` commands - settings are validated on startup

## Generating .env.example

The `.env.example` file is **auto-generated** from the `Settings` class:

```bash
just gen-env
```

This ensures the example file always matches the actual settings defined in code.
Never edit `.env.example` manually - update `packages/aef-shared/src/aef_shared/settings/config.py` instead.

## Environment Variables

### Application

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_ENVIRONMENT` | No | `development` | Environment: `development`, `staging`, `production`, `test` |
| `DEBUG` | No | `false` | Enable debug mode (never in production) |

### Database (PostgreSQL)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Production | None | PostgreSQL connection URL. Format: `postgresql://user:password@host:port/database` |
| `DATABASE_POOL_SIZE` | No | `5` | Connection pool size |
| `DATABASE_POOL_OVERFLOW` | No | `10` | Max overflow connections |

### Event Store (gRPC)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EVENT_STORE_URL` | Production | None | gRPC URL for event store. Format: `grpc://host:port` |
| `EVENT_STORE_TIMEOUT_SECONDS` | No | `30` | Timeout for gRPC calls |

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

### Storage (S3/Supabase)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARTIFACT_STORAGE_TYPE` | No | `database` | Backend: `database` or `s3` |
| `S3_BUCKET_NAME` | For S3 | None | S3 bucket name |
| `S3_ENDPOINT_URL` | For Supabase | None | S3-compatible endpoint |
| `S3_ACCESS_KEY_ID` | For S3 | None | S3 access key |
| `S3_SECRET_ACCESS_KEY` | For S3 | None | S3 secret key |

### GitHub App (Secure Agent Commits)

For secure, auto-rotating tokens with clear audit trails. See [GitHub App Setup Guide](deployment/github-app-setup.md).

| Variable | Required | Default | Description | Where to Get |
|----------|----------|---------|-------------|--------------|
| `AEF_GITHUB_APP_ID` | For GitHub App | None | GitHub App ID | [github.com/settings/apps](https://github.com/settings/apps) |
| `AEF_GITHUB_APP_NAME` | No | `aef-app` | App name for commit attribution (shows as `<name>[bot]`) | Your app's slug |
| `AEF_GITHUB_PRIVATE_KEY` | For GitHub App | None | PEM-format private key | Generate from app settings |
| `AEF_GITHUB_INSTALLATION_ID` | For GitHub App | None | Installation ID | From installation URL |
| `AEF_GITHUB_WEBHOOK_SECRET` | For webhooks | None | Webhook signature secret | Set during app creation |

> **Note:** If any of `AEF_GITHUB_APP_ID`, `AEF_GITHUB_PRIVATE_KEY`, or `AEF_GITHUB_INSTALLATION_ID` is set, all three are required.

## Example .env File

```bash
# Application
APP_ENVIRONMENT=development
DEBUG=false

# Database (leave empty for in-memory in dev)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aef

# Event Store (leave empty for in-memory in dev)
EVENT_STORE_URL=

# Logging
LOG_LEVEL=DEBUG
LOG_FORMAT=console

# Agents
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=

# Storage
ARTIFACT_STORAGE_TYPE=database

# GitHub App (optional - for secure agent commits)
# AEF_GITHUB_APP_ID=123456
# AEF_GITHUB_APP_NAME=aef-app
# AEF_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
# AEF_GITHUB_INSTALLATION_ID=12345678
# AEF_GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

## Usage in Code

```python
from aef_shared import get_settings

# Settings are validated on first access
settings = get_settings()

# Access settings
if settings.is_development:
    print("Running in dev mode")

if settings.database_url:
    # Connect to database
    pass
else:
    # Use in-memory storage
    pass

# Secrets are protected
if settings.anthropic_api_key:
    api_key = settings.anthropic_api_key.get_secret_value()

# GitHub App settings
if settings.github.is_configured:
    print(f"Commits will show as: {settings.github.bot_name}")
```

## Validation

Settings are validated immediately when accessed. If a required variable is missing or invalid, you'll get a clear error:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
database_url
  Field required [type=missing, input_value={}, input_type=dict]
```
