# Local Development Guide

This guide explains how to set up and run the Syntropic137 locally.

> **📦 For Production/Self-Host**: If you're deploying to a self-hosted or production environment, see:
> - [Self-Host Deployment Guide](infra/docs/selfhost-deployment.md) - Docker Compose + Cloudflare Tunnel
> - [Production Deployment Guide](deployment/production-deployment.md) - Workspace isolation options

## Quick Start

The fastest path from clone to running stack:

```bash
# 1. Clone the repository
git clone --recursive https://github.com/syntropic137/syntropic137.git
cd syntropic137

# 2. One-command setup (env, deps, GitHub App, webhook proxy, dev stack)
just onboard-dev
```

This handles submodules, `.env` creation, Python deps, GitHub App registration,
webhook proxy (smee.io), and starts the full dev stack.

**Options:**
- `just onboard-dev --tunnel` — use Cloudflare tunnel instead of smee.io for webhooks
- `just onboard-dev --skip-github` — skip GitHub App setup
- `just onboard-dev --1password` — integrate with 1Password for portable secrets

**Manual setup** (if you prefer step-by-step):

```bash
cp .env.example .env
# Edit .env with your API keys
just dev
```

> **Note:** Trigger-based workflows (GitHub webhook events) require GitHub App
> configuration and webhook delivery. Run `just onboard-dev` to set this up
> automatically, or see the [GitHub App Setup Guide](deployment/github-app-setup.md).

## Development Environment

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker and Docker Compose
- Git

### Environment Types

| Environment | Storage | Use Case |
|-------------|---------|----------|
| **Test** (`APP_ENVIRONMENT=test`) | In-memory | Unit tests, fast feedback |
| **Development** (`APP_ENVIRONMENT=development`) | PostgreSQL (Docker) | Local development |
| **Production** (`APP_ENVIRONMENT=production`) | PostgreSQL (Cloud) | Production workloads |

### Starting Development Services

```bash
# Start all services (PostgreSQL)
just dev

# View logs
just dev-logs

# Stop services
just dev-down

# Reset database (deletes all data)
just dev-reset
```

### Database Connection

When Docker is running, PostgreSQL is available at:

```
postgresql://syn:syn_dev_password@localhost:5432/syn
```

Add these to your `.env` file:

```bash
ESP_EVENT_STORE_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn
SYN_OBSERVABILITY_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn
```

### Running the CLI

```bash
# All CLI commands
just cli --help

# Workflow commands
just cli workflow --help
just cli workflow create "My Workflow"
just cli workflow seed --dry-run
just cli workflow validate workflows/examples/research.yaml

# Execute a workflow with a task (ISS-211: CC command pattern)
just cli workflow run research-workflow-v2 --task "Investigate how auth middleware works"
just cli workflow run research-workflow-v2 --task "$(gh issue view 42 --json body -q .body)" --input topic=auth

# Direct execution
uv run syn --help
```

## Testing

### Running Tests

```bash
# All tests
just test

# With coverage
just test-cov

# Full QA (lint, format, typecheck, test)
just qa
```

### Test Categories

Tests use markers for categorization:

```python
@pytest.mark.unit        # Unit tests (fast, no external deps)
@pytest.mark.integration # Integration tests (may use Docker)
@pytest.mark.e2e         # End-to-end tests (full system)
```

Run specific categories:

```bash
uv run pytest -m unit
uv run pytest -m integration
```

## Project Structure

```
syntropic137/
├── apps/
│   └── syn-cli/              # CLI application
├── packages/
│   ├── syn-domain/           # Domain model (aggregates, events)
│   ├── syn-adapters/         # External integrations
│   └── syn-shared/           # Shared utilities (logging, settings)
├── lib/
│   ├── event-sourcing-platform/  # Event sourcing SDK (submodule)
│   └── agentic-primitives/       # Primitives library (submodule)
├── workflows/
│   ├── examples/             # Example workflow YAML files
│   └── custom/               # Custom workflows (gitignored)
├── docker/
│   ├── docker-compose.dev.yaml
│   └── init-db/              # Database initialization scripts
├── docs/
│   └── adrs/                 # Architecture Decision Records
└── justfile                  # Task runner commands
```

## Troubleshooting

### Docker Issues

```bash
# Check if containers are running
docker ps

# View container logs
docker logs syn-postgres

# Restart services
just dev-reset
```

### Database Issues

```bash
# Connect to database directly
docker exec -it syn-postgres psql -U syn -d syn

# Check tables
\dt event_store.*
\dt public.*
```

### Import Errors

```bash
# Ensure dependencies are synced
uv sync

# Check package installation
uv pip list | grep syn
```

## Making Changes

1. Create a feature branch
2. Make changes following [RIPER-5 guidelines](.cursor/rules/riper-5.md)
3. Run `just qa` to validate
4. Commit with conventional commits
5. Create a PR

See [Contributing Guidelines](../CONTRIBUTING.md) for more details.
