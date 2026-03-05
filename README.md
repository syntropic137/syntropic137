<p align="center">
  <img src="./docs/banner-syntropic137.png" alt="Syntropic137 Banner" width="100%" />
</p>

# Syntropic137

Orchestrates AI agent execution in isolated Docker workspaces and captures every event for observability.

## Quick Start: Dev Mode

For contributors and local hacking. Runs services on your host with hot-reload.

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), Docker

```bash
git clone --recurse-submodules https://github.com/syntropic137/syntropic137.git
cd syntropic137
cp .env.example .env            # fill in ANTHROPIC_API_KEY + GitHub App keys
just dev                        # syncs deps, builds containers, seeds data, starts everything
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |

Use `just dev-fresh` instead for a clean slate (wipes volumes and re-seeds).

## Quick Start: Selfhost

For permanent installs on your own hardware. Everything runs behind an nginx gateway on a single port.

```bash
git clone --recurse-submodules https://github.com/syntropic137/syntropic137.git
cd syntropic137
just onboard                    # interactive wizard — creates .env, checks prerequisites
just selfhost-up                # builds and starts the full stack
```

Access: http://localhost:8008 (configurable via `SYN_GATEWAY_PORT`)

**With Cloudflare Tunnel** (external access):

```bash
just selfhost-up-tunnel         # includes cloudflared service
```

Access: `https://your-domain.com` (configure tunnel route to `http://gateway:80`)

> **Security:** The API has no built-in auth. Protect with Cloudflare Access, nginx basic auth (`SYN_API_PASSWORD`), or a VPN.

| Command | What it does |
|---------|--------------|
| `just selfhost-status` | Health check |
| `just selfhost-logs` | Tail logs |
| `just selfhost-down` | Stop everything |
| `just selfhost-update` | Pull latest, rebuild, restart |
| `just selfhost-reset` | Wipe and start fresh |

## Architecture

![Syn137 Architecture](./docs/architecture/vsa-overview.svg)

<details>
<summary>Bounded Contexts</summary>

| Context | Aggregates | Purpose |
|---------|------------|---------|
| **Orchestration** | Workspace, Workflow, WorkflowExecution | Workflow execution and workspace management |
| **Agent Sessions** | AgentSession | Agent sessions and observability metrics |
| **GitHub** | Installation, TriggerRule | GitHub App integration, webhook trigger rules |
| **Artifacts** | Artifact | Artifact storage and retrieval |

**Infrastructure:** TimescaleDB · EventStore (Rust gRPC) · Redis · MinIO

Regenerate diagram: `just diagram`

</details>

## CLI (`syn`)

```bash
just cli -- <command>           # run via just
# or install: uv tool install -e apps/syn-cli
```

### Workflows

```bash
syn workflow list
syn workflow show <id>
syn workflow run <id> --input key=value
syn workflow status <id>
syn workflow validate path/to/workflow.yaml
syn run <id> -i key=value       # shortcut
```

### Execution Control

```bash
syn control status <execution-id>
syn control pause <execution-id> --reason "investigating"
syn control resume <execution-id>
syn control cancel <execution-id>
```

### Agents

```bash
syn agent list
syn agent test --provider claude --prompt "Hello"
syn agent chat --provider claude
```

### Trigger Rules

```bash
syn triggers register --name "self-healing" --event "check_run.completed" --repository owner/repo --workflow <id>
syn triggers list --repository owner/repo
syn triggers enable <name> --repository owner/repo
syn triggers pause <id> --reason "maintenance"
```

### Config

```bash
syn config show
syn config validate
syn config env
syn version
```

## Development Commands

| Command | Description |
|---------|-------------|
| `just dev` | Start full dev stack (deps, containers, seeds, frontend) |
| `just dev-fresh` | Wipe volumes, rebuild, re-seed — clean slate |
| `just dev-down` | Stop all services |
| `just dev-logs` | Tail service logs |
| `just dev-doctor` | Check environment health |
| | |
| `just qa` | Full QA: lint, format, typecheck, test, vsa-validate |
| `just test` | Run tests with coverage |
| `just test-unit` | Unit tests only |
| `just test-integration` | Integration tests (needs test-stack) |
| `just test-stack` | Spin up ephemeral test infrastructure |
| `just lint` | Ruff linter |
| `just format` | Ruff formatter |
| `just typecheck` | mypy strict |
| `just vsa-validate` | Validate Vertical Slice Architecture |
| | |
| `just submodules-init` | Initialize git submodules |
| `just submodules-update` | Pull latest submodule commits |
| `just diagram` | Regenerate architecture SVG |
| `just seed-workflows` | Seed workflow definitions |
| `just seed-triggers` | Seed trigger rules |

## Project Structure

```
syntropic137/
├── apps/
│   ├── syn-api/                 # FastAPI HTTP server
│   ├── syn-cli/                 # CLI tool ("syn")
│   └── syn-dashboard-ui/        # Dashboard frontend (Vite + React)
├── packages/
│   ├── syn-domain/              # Domain events, aggregates, ports
│   ├── syn-adapters/            # Orchestration + observability adapters
│   ├── syn-collector/           # Event ingestion API
│   └── syn-shared/              # Settings, configuration
├── lib/                         # Git submodules (our own projects)
│   ├── agentic-primitives/      # Agent building blocks, isolation providers
│   └── event-sourcing-platform/ # Rust event store, Python SDK, VSA tool
├── infra/                       # Docker Compose, setup wizard, secrets
├── docker/                      # Compose files (base, dev, selfhost, test)
└── docs/                        # Documentation and ADRs
```

## Secrets (1Password)

1Password integration is optional. Set `APP_ENVIRONMENT` to auto-derive the vault name:

| `APP_ENVIRONMENT` | Vault |
|-------------------|-------|
| `development` | `syn137-dev` |
| `beta` | `syn137-beta` |
| `staging` | `syn137-staging` |
| `production` | `syn137-prod` |

Provide the matching service account token (e.g. `OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV`) and all secrets resolve automatically. Anything not in 1Password falls through to `.env` plaintext.

**Precedence:** shell env > 1Password > `.env` file

Full setup guide: [docs/development/1password-secrets.md](docs/development/1password-secrets.md)

## License

MIT
