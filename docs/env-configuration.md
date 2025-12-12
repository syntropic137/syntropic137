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

### GitHub App (Secure Agent Authentication)

For production deployments, use a GitHub App instead of Personal Access Tokens. See [GitHub App Setup](deployment/github-app-setup.md) for detailed instructions.

| Variable | Required | Default | Description | Where to Get |
|----------|----------|---------|-------------|--------------|
| `AEF_GITHUB_APP_ID` | For GitHub App | None | Numeric App ID | App settings → General |
| `AEF_GITHUB_APP_NAME` | For GitHub App | None | App slug (e.g., `aef-engineer-beta`) | App settings → General |
| `AEF_GITHUB_INSTALLATION_ID` | For GitHub App | None | Installation ID per org | Settings → Installations → Configure URL |
| `AEF_GITHUB_PRIVATE_KEY` | For GitHub App | None | RSA private key (PEM format) | App settings → Private keys → Generate |
| `AEF_GITHUB_WEBHOOK_SECRET` | For webhooks | None | HMAC secret for webhook verification | Set during app creation |

### Git Identity (Commit Attribution)

Used for git commits in isolated workspaces. Can be auto-derived from GitHub App settings.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AEF_GIT_USER_NAME` | For commits | None | Git committer name (e.g., `aef-bot[bot]`) |
| `AEF_GIT_USER_EMAIL` | For commits | None | Git committer email |
| `AEF_GIT_TOKEN` | Legacy | None | GitHub PAT (prefer GitHub App instead) |

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

# GitHub App (for production - see docs/deployment/github-app-setup.md)
AEF_GITHUB_APP_ID=2461312
AEF_GITHUB_APP_NAME=aef-engineer-beta
AEF_GITHUB_INSTALLATION_ID=99311335
AEF_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
...your private key...
-----END RSA PRIVATE KEY-----"
# AEF_GITHUB_WEBHOOK_SECRET=your-webhook-secret

# Git Identity (auto-derived from GitHub App, or set manually)
AEF_GIT_USER_NAME=aef-engineer-beta[bot]
AEF_GIT_USER_EMAIL=2461312+aef-engineer-beta[bot]@users.noreply.github.com
```

## Usage in Code

```python
from aef_shared.settings import get_settings

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
github = settings.github
if github.is_configured:
    print(f"GitHub App: {github.app_name}")
    print(f"Bot: {github.bot_username}")  # e.g., aef-engineer-beta[bot]
    print(f"Email: {github.bot_email}")   # e.g., 123+app[bot]@users.noreply.github.com

# Git identity for commits
git = settings.git_identity
if git.is_configured:
    print(f"Commits as: {git.user_name} <{git.user_email}>")
```

## Validation

Settings are validated immediately when accessed. If a required variable is missing or invalid, you'll get a clear error:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
database_url
  Field required [type=missing, input_value={}, input_type=dict]
```
