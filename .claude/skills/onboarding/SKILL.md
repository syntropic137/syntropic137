# Skill: Onboarding — Syntropic137 Setup Knowledge

Everything an agent needs to get a developer from `git clone` to a running Syntropic137 stack.

## Prerequisites

### Required Tools

| Tool | Detect | Install (macOS) | Install (Linux) |
|------|--------|-----------------|-----------------|
| Docker Desktop | `docker info` | `brew install --cask docker` | [docs.docker.com](https://docs.docker.com/engine/install/) |
| uv | `uv --version` | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| just | `just --version` | `brew install just` | `cargo install just` or prebuilt binary |
| pnpm | `pnpm --version` | `brew install pnpm` | `npm install -g pnpm` |
| git | `git --version` | Xcode CLI tools | `apt install git` |
| Node.js >=18 | `node --version` | `brew install node` | `nvm install --lts` |

### Optional Tools

| Tool | When Needed | Detect |
|------|-------------|--------|
| 1Password CLI (`op`) | Secrets management | `op --version` |
| Rust toolchain | Building event-store server | `cargo --version` |
| smee-client | GitHub webhook dev | `npx smee --version` |

## Environment Detection Checklist

Use these checks to determine what's already configured:

### Files & Configuration
- **`.env` exists and has values**: `test -f .env && grep -q '=' .env` — application config (API keys, GitHub creds, logging)
- **`infra/.env` exists**: `test -f infra/.env` — infrastructure config only (Compose, resource limits, tunnel). Needed for selfhost only
- **Git submodules initialized**: `test -d lib/agentic-primitives/.git && test -d lib/event-sourcing-platform/.git`
- **Python deps installed**: `uv sync --dry-run 2>&1 | grep -q 'Already'` or check `.venv/` exists

### Services & Runtime
- **Docker running**: `docker info >/dev/null 2>&1`
- **Workspace image built**: `docker images agentic-workspace-claude-cli --format '{{.Repository}}' | grep -q agentic`
- **Dev stack running**: `docker ps --format '{{.Names}}' | grep -q syn`
- **Ports available**: `lsof -i :8000 -i :5432 -i :50051 -i :5173 2>/dev/null`

### 1Password (optional)
- **CLI installed**: `command -v op`
- **Service account configured**: Check for `OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV` in env or `.env`
- **Vault accessible**: `op vault list 2>/dev/null | grep -q syn137`

## Setup Paths

### Path 1: Dev (Local Hacking)

For contributors working on Syntropic137 code. Lightweight, fast iteration.

**One command:**
```bash
just onboard-dev
```

This handles everything: submodules, `.env` with dev defaults, Python deps, dashboard deps, GitHub App setup, workspace image build, and starts `just dev`. The Docker image builds in the background while you configure the GitHub App interactively.

**Flags:**
```bash
just onboard-dev --skip-github  # Skip GitHub App setup
just onboard-dev --tunnel       # Also configure Cloudflare tunnel
just onboard-dev --1password    # Also configure 1Password service account
```

**What `just onboard-dev` does (step by step):**
1. Init git submodules (skipped if already done)
2. Create `.env` from template with dev defaults (skipped if exists)
3. `uv sync` — install Python dependencies (skipped if `.venv/` exists)
4. `just dashboard-install` — install frontend dependencies (skipped if `node_modules/` exists)
5. Build workspace Docker image in background (skipped if already built)
6. Webhook URL setup — Cloudflare tunnel (`--tunnel`) or auto-provision smee.io channel (automatic, zero manual steps)
7. 1Password setup — configure service account token (only with `--1password` flag)
8. GitHub App setup — interactive wizard stage, now has webhook URL available (skipped if already configured or `--skip-github`)
9. Wait for workspace image build (if started)
10. `just dev` — start the full dev stack

**Verify** — see [Post-Setup Verification](#post-setup-verification)

### Path 2: Selfhost (Production Deployment)

Full production setup with secrets, Cloudflare tunnel, GitHub App.

**Steps:**

1. **Run the onboarding wizard**
   ```bash
   just onboard
   ```
   The wizard (`infra/scripts/setup.py`) handles:
   - Prerequisite checks
   - Submodule initialization
   - Secret generation
   - 1Password configuration (optional)
   - Cloudflare tunnel setup (optional)
   - GitHub App configuration (optional)
   - Smee webhook proxy (optional)

2. **Start selfhost stack**
   ```bash
   just selfhost-up
   ```
   Or with Cloudflare tunnel:
   ```bash
   just selfhost-up-tunnel
   ```

3. **Seed initial data** (optional)
   ```bash
   just selfhost-seed
   ```

4. **Verify** — see [Post-Setup Verification](#post-setup-verification)

**Wizard flags:**
- `just onboard --skip-github` — skip GitHub App setup
- `just onboard --non-interactive` — use values from env / `.env`
- `just onboard --stage <name>` — re-run a single stage
- `just setup-check` — check prerequisites only (no changes)

## Key Environment Variables

### Always Required (Dev)

| Variable | Purpose | Dev Default |
|----------|---------|-------------|
| `APP_ENVIRONMENT` | Controls logging, features, vault selection | `development` |
| `ESP_EVENT_STORE_DB_URL` | Event sourcing database | `postgresql://syn:syn_dev_password@localhost:5432/syn` |
| `SYN_OBSERVABILITY_DB_URL` | Dashboard/metrics database | Same as ESP (ADR-030 consolidation) |

### For Agent Execution

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access (or use `CLAUDE_CODE_OAUTH_TOKEN`) |
| `SYN_WORKSPACE_DOCKER_IMAGE` | Workspace container image |

### For GitHub Integration

| Variable | Purpose |
|----------|---------|
| `SYN_GITHUB_APP_ID` | GitHub App ID |
| `SYN_GITHUB_PRIVATE_KEY` | Base64-encoded `.pem` key |
| `SYN_GITHUB_WEBHOOK_SECRET` | Webhook payload verification |

### 1Password (Optional)

| Variable | Purpose |
|----------|---------|
| `OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV` | Per-vault service account token |
| `APP_ENVIRONMENT` | Determines vault: `development` → `syn137-dev` |

See `.env.example` for the complete list with descriptions.

## Common Errors and Fixes

### Docker Not Running
**Symptom:** `Cannot connect to the Docker daemon`
**Fix:** Start Docker Desktop, then retry. On Linux: `sudo systemctl start docker`

### Port Conflict
**Symptom:** `Bind for 0.0.0.0:8000 failed: port is already allocated`
**Fix:** Stop the conflicting process or change `DASHBOARD_PORT` in `.env`. Check ports: `lsof -i :8000`

### Missing `.env`
**Symptom:** `Error: .env file not found` or services fail with missing config
**Fix:** `cp .env.example .env` and fill in required values (see [Key Environment Variables](#key-environment-variables))

### Submodule Issues
**Symptom:** Empty `lib/` directories, import errors for `event_sourcing` or `agentic_primitives`
**Fix:** `just submodules-init` — if that fails: `git submodule update --init --recursive`

### uv Sync Fails
**Symptom:** `uv sync` errors about missing packages
**Fix:** Ensure uv is up to date (`uv self update`), then `uv sync` again. Check Python 3.12+ is available.

### Workspace Image Not Found
**Symptom:** Agent execution fails with image not found
**Fix:** `just workspace-build`

### Database Connection Refused
**Symptom:** `Connection refused` on port 5432
**Fix:** Ensure dev stack is running (`just dev`) — TimescaleDB runs inside Docker.

## Post-Setup Verification

After setup, verify these endpoints:

| Service | URL | Expected |
|---------|-----|----------|
| Dashboard UI | http://localhost:5173 | Vite React app loads |
| Dashboard API | http://localhost:8137/docs | FastAPI Swagger UI |
| API Health | http://localhost:8137/health | `{"status": "ok"}` |
| Event Store gRPC | localhost:50051 | gRPC server listening |

Quick health check:
```bash
just health-check
```

JSON output:
```bash
just health-json
```

## Just Recipes Reference

### Onboarding
| Recipe | Purpose |
|--------|---------|
| `just onboard-dev` | Dev onboarding: submodules, .env, deps, GitHub App, stack |
| `just onboard-dev --skip-github` | Dev onboarding without GitHub App setup |
| `just onboard-dev --tunnel` | Dev onboarding + Cloudflare tunnel setup |
| `just onboard-dev --1password` | Dev onboarding + 1Password service account setup |
| `just onboard` | Full interactive selfhost wizard |
| `just setup-check` | Check prerequisites only |
| `just setup-stage <stage>` | Re-run a specific wizard stage |

### Development
| Recipe | Purpose |
|--------|---------|
| `just dev` | Start full dev stack (rebuild images) |
| `just dev-fresh` | Clean rebuild — wipe volumes, rebuild everything |
| `just dev-stop` | Stop services (keep volumes) |
| `just dev-down` | Stop and remove services |
| `just dev-logs` | Tail all service logs |
| `just dev-doctor` | Diagnose environment issues |

### Selfhost
| Recipe | Purpose |
|--------|---------|
| `just selfhost-up` | Start production stack |
| `just selfhost-up-tunnel` | Start with Cloudflare tunnel |
| `just selfhost-down` | Stop production stack |
| `just selfhost-status` | Show service status |
| `just selfhost-logs` | Tail service logs |
| `just selfhost-seed` | Seed initial data |
| `just selfhost-update` | Pull latest and redeploy |
| `just selfhost-reset` | Full reset (destructive) |

### Dependencies & Build
| Recipe | Purpose |
|--------|---------|
| `just submodules-init` | Initialize git submodules |
| `just submodules-update` | Update submodules to latest |
| `just sync` | Sync all dependencies (uv + pnpm) |
| `just workspace-build` | Build agent workspace Docker image |
| `just dashboard-install` | Install dashboard frontend deps |

### QA & Testing
| Recipe | Purpose |
|--------|---------|
| `just qa` | Full QA suite (lint, format, types, tests) |
| `just test` | Run all tests |
| `just test-unit` | Unit tests only |
| `just test-integration` | Integration tests |
| `just health-check` | Verify running services |
