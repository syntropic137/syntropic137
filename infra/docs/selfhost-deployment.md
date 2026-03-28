# Self-Host Deployment Guide

Complete guide for deploying Syntropic137 on a self-hosted server (Mac Mini, Linux box, etc.) with secure external access via Cloudflare Tunnel.

## Overview

This deployment provides:
- **Full Syn137 stack**: Dashboard UI, Pulse UI, API, Event Store, PostgreSQL
- **Secure external access**: Via Cloudflare Tunnel (no port forwarding)
- **Automatic restarts**: Services restart on failure or reboot
- **Log management**: Automatic log rotation

## Prerequisites

### Hardware
- Mac Mini, Linux server, or any Docker-capable machine
- Minimum 4GB RAM, 20GB storage
- Stable internet connection

### Software
- Docker 24+ with Docker Compose v2
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- [just](https://github.com/casey/just) command runner

> **New machine?** Run the bootstrap script to install all prerequisites automatically:
> ```bash
> curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/Syntropic137/syntropic137/main/infra/scripts/bootstrap.sh | bash
> ```

### Accounts
- [Cloudflare account](https://dash.cloudflare.com/) with a domain (recommended — free TLS, DDoS protection, no port forwarding)
- [GitHub App](../../../docs/deployment/github-app-setup.md) configured

## Step-by-Step Deployment

### Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/syntropic137/syntropic137.git
cd syntropic137

# Initialize submodules
git submodule update --init --recursive

# Install dependencies
uv sync
```

### Step 2: Generate Secrets

```bash
# Generate DB/Redis passwords (auto-generated, file-based Docker secrets)
just secrets-generate

# Verify secrets were created
just secrets-check
```

### Step 3: Run Setup Wizard

The setup wizard configures GitHub App credentials, Cloudflare Tunnel, and writes everything to `infra/.env`:

```bash
just onboard
```

This handles:
- GitHub App private key (`file:` path reference, base64, or raw PEM in `.env` — or resolved from 1Password)
- Webhook secret (generated and stored in `.env` or resolved from 1Password)
- Cloudflare tunnel token (stored in `.env` or resolved from 1Password)

### Step 4: Configure Cloudflare Tunnel

#### Option A: Via Cloudflare Dashboard (Recommended)

1. Go to [Cloudflare Dashboard — Tunnels](https://dash.cloudflare.com/?to=/:account/tunnels)
2. Navigate to **Networks** → **Tunnels** → **Create a tunnel**
3. Name it: `syn-selfhost`
4. Copy the tunnel token to your `.env`:

```bash
# Add to infra/.env
CLOUDFLARE_TUNNEL_TOKEN=eyJ...your-token...
```

Add these routes in the tunnel configuration:

| Subdomain | Domain | Service |
|-----------|--------|---------|
| `syn137` | yourdomain.com | `http://gateway:8081` |

#### Option B: Via CLI

```bash
# Install cloudflared
brew install cloudflared  # macOS
# or see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create syn-selfhost
cloudflared tunnel route dns syn-selfhost syn137.yourdomain.com
cloudflared tunnel route dns syn-selfhost api.syn137.yourdomain.com

# Get token
cloudflared tunnel token syn-selfhost
```

### Step 5: Configure Environment

```bash
# Copy environment template
cp infra/.env.example infra/.env

# Edit with your values
nano infra/.env  # or your preferred editor
```

Required settings:

```bash
# Domain
SYN_DOMAIN=syn137.yourdomain.com

# GitHub App
SYN_GITHUB_APP_ID=123456
SYN_GITHUB_APP_NAME=your-app-name
```

> **Note**: Crown-jewel secrets (GitHub PEM, webhook secret, tunnel token)
> are stored in `infra/.env` or resolved from 1Password — not as Docker secret files.

### Step 6: Deploy

```bash
# Start the self-host stack with Cloudflare Tunnel (recommended)
just selfhost-up-tunnel

# This will:
# 1. Build all Docker images
# 2. Start services (including cloudflared)
# 3. Wait for health checks
# 4. Display status
```

> **No Cloudflare?** Use `just selfhost-up` for local-only access (no tunnel).
> The `selfhost-update` and `selfhost-down` commands auto-detect which mode you're running.

### Step 7: Verify Deployment

```bash
# Check service status
just selfhost-status

# Check tunnel status
just selfhost-tunnel-status

# Test external access
curl https://syn137.yourdomain.com/health
curl https://api.syn137.yourdomain.com/health
```

## Management Commands

### Daily Operations

```bash
# View all logs
just selfhost-logs

# View specific service logs
just selfhost-logs api
just selfhost-logs cloudflared

# Check health
just health-check

# Restart a service
just selfhost-restart api
```

### Updates

```bash
# Pull latest code
git pull

# Upgrade stack (rebuilds images)
just selfhost-update
```

### Troubleshooting

```bash
# Check detailed status
docker ps -a

# View container logs
docker logs ${COMPOSE_PROJECT_NAME:-syntropic137}-api

# Enter container for debugging
docker exec -it ${COMPOSE_PROJECT_NAME:-syntropic137}-api /bin/bash

# Full reset (WARNING: deletes data)
just selfhost-reset
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Internet                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Cloudflare Network                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   WAF/DDoS  │  │     TLS     │  │   Caching   │             │
│  │  Protection │  │ Termination │  │             │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (Cloudflare Tunnel)
┌─────────────────────────────────────────────────────────────────┐
│                     Your Self-Host                               │
│                                                                  │
│  ┌──────────────┐    ┌──────────────────────────┐               │
│  │  cloudflared │───▶│        gateway           │               │
│  │              │    │   (nginx reverse proxy)   │               │
│  └──────────────┘    │  /       → Dashboard UI   │               │
│                      │  /pulse/ → Pulse UI       │               │
│                      │  /api/v1/→ API proxy      │               │
│                      └──────────────────────────┘               │
│                                    │                             │
│                                    ▼                             │
│                            ┌──────────────┐                     │
│                            │     api      │                     │
│                            │  (FastAPI)   │                     │
│                            └──────────────┘                     │
│                                                 │                │
│                           ┌─────────────────────┼───────────┐   │
│                           ▼                     ▼           │   │
│                    ┌──────────────┐    ┌──────────────┐     │   │
│                    │  event-store │    │  collector   │     │   │
│                    │   (gRPC)     │    │   (HTTP)     │     │   │
│                    └──────────────┘    └──────────────┘     │   │
│                           │                                  │   │
│                           ▼                                  │   │
│                    ┌──────────────┐                         │   │
│                    │ TimescaleDB  │◀────────────────────────┘   │
│                    │              │                              │
│                    └──────────────┘                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Secrets Architecture

Secrets are split into two tiers based on sensitivity and how they're consumed:

### Crown-Jewel Secrets (env vars — never on disk)

These are high-value secrets injected as environment variables. With 1Password
they never touch the filesystem at all.

| Secret | Env Var | Description |
|--------|---------|-------------|
| GitHub private key | `SYN_GITHUB_PRIVATE_KEY` | `file:` path, raw PEM, or base64 |
| Webhook secret | `SYN_GITHUB_WEBHOOK_SECRET` | HMAC signing key |
| Tunnel token | `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare tunnel auth |

**Resolution order:** shell env > 1Password > `infra/.env`

### Infrastructure Secrets (file-based Docker secrets)

These are auto-generated random passwords used by non-Python services
(PostgreSQL, Redis). Low-value, need to persist across restarts.

| Secret | File | Description |
|--------|------|-------------|
| DB password | `infra/docker/secrets/db-password.txt` | PostgreSQL password |
| Redis password | `infra/docker/secrets/redis-password.txt` | Redis auth |

Generated by `just secrets-generate`. No 1Password needed.

### How `just onboard` Handles Secrets

The setup wizard detects what's already configured and skips accordingly:

```
┌─────────────────────────────────────────────────────────┐
│  1. configure_1password  — sets up vault + SA token     │
│  2. validate_environment — checks ALL sources, shows    │
│     table of what's set and where (1Password/.env/file) │
│  3. configure_cloudflare — if token already in          │
│     1Password or .env → skip. Otherwise walks through   │
│     tunnel creation and captures token.                 │
│  4. configure_github_app — if all 4 GitHub keys in      │
│     1Password or .env → skip. Otherwise creates app     │
│     via manifest flow or manual entry.                  │
│  5. configure_env — writes collected values to .env     │
│     (1Password users: .env only needs non-secret        │
│     config like SYN_DOMAIN, APP_ENVIRONMENT)             │
└─────────────────────────────────────────────────────────┘
```

**Re-running is safe.** Each stage checks existing config and offers to keep
or reconfigure. Run `just onboard --stage <name>` to re-run a single stage.

## Deployment Paths

### Path A: With 1Password (Recommended)

Secrets never touch disk. The setup wizard detects 1Password and skips
secret collection for anything already in the vault.

```
just onboard
  → configures 1Password (vault derived from APP_ENVIRONMENT)
  → detects GitHub secrets in vault → skips
  → detects tunnel token in vault → skips (or creates tunnel)
  → writes minimal .env (SYN_DOMAIN, APP_ENVIRONMENT, etc.)

just selfhost-up
  → APP_ENVIRONMENT=development → vault syn137-dev
  → op_env_export.py resolves secrets from vault
  → docker compose interpolates env vars
  → containers receive secrets as env vars (tmpfs only)
```

**What to store in your 1Password `syntropic137-config` item:**
- `SYN_GITHUB_APP_ID`
- `SYN_GITHUB_APP_NAME`
- `SYN_GITHUB_PRIVATE_KEY` (`file:` path, raw PEM, or base64)
- `SYN_GITHUB_WEBHOOK_SECRET`
- `CLOUDFLARE_TUNNEL_TOKEN`
- `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`

### Path B: Without 1Password

Secrets live in `infra/.env` (gitignored, 600 perms). The setup wizard
collects everything interactively and writes it there.

```
just onboard
  → skips 1Password
  → creates GitHub App → base64-encodes PEM → writes to .env
  → creates Cloudflare tunnel → writes token to .env
  → writes full .env with all secrets

just selfhost-up
  → docker compose reads .env
  → containers receive secrets as env vars
```

### Graceful Fallback

If 1Password is not configured, everything works with `.env` plaintext
values. The `op_resolver.py` module silently skips resolution when
`OP_SERVICE_ACCOUNT_TOKEN` is unset.

See `docs/development/1password-secrets.md` for full 1Password documentation.

## Security Considerations

### Network Security
- **No inbound ports**: All traffic goes through Cloudflare Tunnel
- **Encrypted tunnel**: Connection to Cloudflare is encrypted
- **Service isolation**: Services only accessible within Docker network

### Access Control
- Consider adding [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) for authentication
- Configure Cloudflare WAF rules for additional protection

### Secrets
- DB/Redis passwords: file-based Docker secrets (auto-generated, low-value)
- GitHub private key + webhook secret: env vars via `.env` or 1Password (never touch disk as plain files)
- Cloudflare tunnel token: env var via `.env` or 1Password
- Rotate DB/Redis secrets periodically: `just secrets-rotate`
- Encrypt remaining secret files for safe storage: `just secrets-seal`
- Run `just security-audit` to check your overall security posture

### Updates
- Keep Docker images updated: `just selfhost-update`
- Monitor Cloudflare security notifications

## Backup & Recovery

### Database Backup

```bash
# Manual backup
docker exec ${COMPOSE_PROJECT_NAME:-syntropic137}-timescaledb pg_dump -U ${POSTGRES_USER:-syn} ${POSTGRES_DB:-syn} > backup-$(date +%Y%m%d).sql

# Restore
cat backup-20250101.sql | docker exec -i ${COMPOSE_PROJECT_NAME:-syntropic137}-timescaledb psql -U ${POSTGRES_USER:-syn} ${POSTGRES_DB:-syn}
```

### Configuration Backup

Back up these files:
- `infra/.env`
- `infra/docker/secrets/` (encrypted via `just secrets-seal`)
- Any custom compose overrides

> **Tip**: Run `just secrets-seal` to encrypt secrets into `.enc` files that
> are safe to commit to version control. Use `just secrets-unseal` to restore
> plain-text files before starting Docker services.

## Monitoring

### Basic Monitoring

```bash
# Service status
just selfhost-status

# Health check
just health-check

# Resource usage
docker stats
```

### Log Aggregation

Logs are stored with rotation:
- Max size: 10-50MB per file
- Max files: 3-5 per service

View with:
```bash
just selfhost-logs
```

## Common Issues

### Services Not Starting

```bash
# Check for port conflicts
lsof -i :80
lsof -i :8000

# Check Docker resources
docker system df
docker system prune -a  # Clean up (careful!)
```

### Tunnel Not Connecting

```bash
# Check tunnel logs
just selfhost-logs cloudflared

# Verify CLOUDFLARE_TUNNEL_TOKEN is set in infra/.env
grep CLOUDFLARE_TUNNEL_TOKEN infra/.env

# Regenerate token in Cloudflare dashboard if needed
```

### Database Connection Issues

```bash
# Check TimescaleDB health
docker exec ${COMPOSE_PROJECT_NAME:-syntropic137}-timescaledb pg_isready -U ${POSTGRES_USER:-syn}

# Check connection from API container
docker exec ${COMPOSE_PROJECT_NAME:-syntropic137}-api python -c "import asyncpg; print('OK')"
```

## Next Steps

- Set up [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) for authentication
- Configure alerting (email/Slack) for service failures
- Set up automated backups
- Add monitoring with Prometheus/Grafana
