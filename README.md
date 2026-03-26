<p align="center">
  <img src="./public/assets/syn137-banner.png" alt="Syntropic137 Banner" width="100%" />
</p>

# Syntropic137

Orchestrates AI agent execution in isolated Docker workspaces and captures every event for observability.

## Self-Hosting (recommended)

Get your own instance running in minutes. Only prerequisite: **Docker**.

> **Using Claude Code?** Install the plugin — it handles everything:
>
> ```
> /plugin install syntropic137/syntropic137-claude-plugin
> /syn-setup
> ```

### Manual Setup (without Claude Code)

```bash
mkdir -p ~/.syntropic137/secrets && cd ~/.syntropic137
# Download latest release assets
curl -sL https://github.com/syntropic137/syntropic137/releases/latest/download/docker-compose.syntropic137.yaml -o docker-compose.syntropic137.yaml
curl -sL https://github.com/syntropic137/syntropic137/releases/latest/download/syn-ctl -o syn-ctl && chmod +x syn-ctl
curl -sL https://github.com/syntropic137/syntropic137/releases/latest/download/selfhost.env.example -o .env
curl -sL https://github.com/syntropic137/syntropic137/releases/latest/download/selfhost-entrypoint.sh -o selfhost-entrypoint.sh && chmod +x selfhost-entrypoint.sh
# Generate secrets
for s in db-password redis-password minio-password; do openssl rand -hex 32 > secrets/$s.secret; done
chmod 600 secrets/*.secret
# Edit .env — add your ANTHROPIC_API_KEY at minimum
# Start
docker compose -f docker-compose.syntropic137.yaml pull
docker compose -f docker-compose.syntropic137.yaml up -d
```

Access: http://localhost:8137

**Optional features** (add anytime):
- **GitHub App** — PR triggers, code review, workflow automation
- **Cloudflare Tunnel** — remote access + webhook delivery (highly recommended, free; required for GitHub webhook triggers; without it, manual workflow runs only and dashboard on localhost only; domain costs $10-15/year if buying new)
- **1Password** — encrypted secrets management

Run `/syn-setup` again or `./syn-ctl update` to add features later.

> **Security:** Set `SYN_API_PASSWORD` for basic auth. Or protect with Cloudflare Access / VPN.

### Management Commands

| Action | Published path (`~/.syntropic137/`) | Source repo |
|--------|-------------------------------------|-------------|
| Status | `./syn-ctl status` | `just selfhost-status` |
| Logs | `./syn-ctl logs` | `just selfhost-logs` |
| Stop | `./syn-ctl down` | `just selfhost-down` |
| Start | `./syn-ctl up` | `just selfhost-up` |
| Update | `./syn-ctl update` | `git pull && just selfhost-up` |

## For Contributors (Dev Mode)

For hacking on Syntropic137 itself. Runs services on your host with hot-reload.

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), Docker, Git, [Node.js](https://nodejs.org/) + [pnpm](https://pnpm.io/)

```bash
git clone --recurse-submodules https://github.com/syntropic137/syntropic137.git
cd syntropic137
cp .env.example .env            # fill in ANTHROPIC_API_KEY + GitHub App keys
just dev                        # syncs deps, builds containers, seeds data, starts everything
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API | http://localhost:8137 |
| API Docs | http://localhost:8137/docs |
| MinIO Console | http://localhost:9001 |

Use `just dev-fresh` instead for a clean slate (wipes volumes and re-seeds).

## Architecture

The system is organized into 6 bounded contexts following Vertical Slice Architecture (VSA) and DDD principles:

![Syn137 Architecture](./docs/architecture/vsa-overview.svg)

<details>
<summary>Bounded Contexts</summary>

| Context | Aggregates | Purpose |
|---------|------------|---------|
| **Orchestration** | Workspace, Workflow, WorkflowExecution | Workflow execution and workspace management |
| **Organization** | Organization, System, Repo | Organization hierarchy, system and repo management |
| **Agent Sessions** | AgentSession | Agent sessions and observability metrics |
| **GitHub** | Installation, TriggerRule | GitHub App integration, webhook trigger rules |
| **Artifacts** | Artifact | Artifact storage and retrieval |

**Infrastructure:** PostgreSQL (event store + projections) · Redis · MinIO

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
syn workflow run <id> --task "Implement retry logic" --input key=value
syn workflow status <id>
syn workflow validate path/to/workflow.yaml

# Examples
syn workflow run research-workflow-v2 --task "$(gh issue view 211 --json body -q .body)"
syn workflow run github-pr --task "Add error handling" -i repository=owner/repo
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
| `just typecheck` | pyright (standard mode) |
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

## Environment Configuration

Two `.env` files with **strict separation** — no variable appears in both.

```
┌─────────────────────────────────────────────────────────────────┐
│  .env  (root)                                                   │
│  Application config — owned by Pydantic Settings                │
│                                                                 │
│  APP_ENVIRONMENT          SYN_GITHUB_APP_ID                     │
│  ANTHROPIC_API_KEY        SYN_GITHUB_APP_NAME                   │
│  CLAUDE_CODE_OAUTH_TOKEN  SYN_GITHUB_PRIVATE_KEY                │
│  LOG_LEVEL / LOG_FORMAT   SYN_GITHUB_WEBHOOK_SECRET             │
│  OP_SERVICE_ACCOUNT_*     DEV__SMEE_URL                         │
│  ESP_EVENT_STORE_DB_URL   SYN_OBSERVABILITY_DB_URL              │
│  ... (all Settings fields — see .env.example)                   │
├─────────────────────────────────────────────────────────────────┤
│  Read by: Pydantic Settings, op_resolver, just dev,             │
│           selfhost-env.sh (sourced first)                       │
│  Template: .env.example (auto-generated from Settings classes)  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  infra/.env                                                     │
│  Infrastructure config — Docker Compose, deployment tuning      │
│                                                                 │
│  COMPOSE_PROJECT_NAME     CLOUDFLARE_TUNNEL_TOKEN               │
│  POSTGRES_PASSWORD/DB/USER  SYN_DOMAIN                          │
│  MINIO_ROOT_USER/PASSWORD INCLUDE_OP_CLI                        │
│  REDIS_PASSWORD           SYN_GATEWAY_PORT                      │
│  Resource limits (API_MEMORY_LIMIT, etc.)                       │
│  Backup settings, PG tuning                                     │
├─────────────────────────────────────────────────────────────────┤
│  Read by: Docker Compose, selfhost-env.sh (sourced second)      │
│  Template: infra/.env.example (manually maintained)             │
└─────────────────────────────────────────────────────────────────┘

        ┌──────────────────────────────┐
        │  selfhost-env.sh             │
        │  1. source .env              │
        │  2. source infra/.env        │
        │  3. Derive vault from        │
        │     APP_ENVIRONMENT          │
        │  4. Load 1Password token     │
        │  5. Resolve 1Password →      │
        │     export to env            │
        └──────────────────────────────┘
```

| Workflow | Root `.env` | `infra/.env` |
|----------|------------|-------------|
| `just onboard-dev` | Created from `.env.example` | Not needed |
| `just dev` | Read via `env_file` | Not used |
| `just onboard` (selfhost) | Created, app config | Created, infra config |
| `just selfhost-up` | Sourced first | Sourced second |

## Secrets (1Password)

1Password integration is optional. Set `APP_ENVIRONMENT` to auto-derive the vault name:

| `APP_ENVIRONMENT` | Vault |
|-------------------|-------|
| `development` | `syn137-dev` |
| `beta` | `syn137-beta` |
| `staging` | `syn137-staging` |
| `production` | `syn137-prod` |
| `selfhost` | `syntropic137` |

Provide the matching service account token (e.g. `OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV`) and all secrets resolve automatically. Anything not in 1Password falls through to `.env` plaintext.

**Precedence:** shell env > 1Password > `.env` file

Full setup guide: [docs/development/1password-secrets.md](docs/development/1password-secrets.md)

## License

MIT
