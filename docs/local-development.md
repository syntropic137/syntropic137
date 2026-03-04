# Local Development Guide

This guide explains how to set up and run the Syntropic137 locally.

> **📦 For Production/Self-Host**: If you're deploying to a self-hosted or production environment, see:
> - [Self-Host Deployment Guide](infra/docs/selfhost-deployment.md) - Docker Compose + Cloudflare Tunnel
> - [Production Deployment Guide](deployment/production-deployment.md) - Workspace isolation options

## Quick Start

```bash
# 1. Clone the repository
git clone --recursive https://github.com/syntropic137/syntropic137.git
cd syntropic137

# 2. Install dependencies
uv sync

# 3. Start Docker services (PostgreSQL)
just dev

# 4. Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# 5. Seed example workflows
just cli workflow seed

# 6. Verify setup
just cli workflow list
```

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
postgresql://syn137:syn137_dev_password@localhost:5432/syn137
```

Add this to your `.env` file:

```bash
DATABASE_URL=postgresql://syn137:syn137_dev_password@localhost:5432/syn137
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
docker exec -it syn-postgres psql -U syn137 -d syn137

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
