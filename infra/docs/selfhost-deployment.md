# Self-Host Deployment Guide

Complete guide for deploying Syntropic137 on a self-hosted server (Mac Mini, Linux box, etc.) with secure external access via Cloudflare Tunnel.

## Overview

This deployment provides:
- **Full AEF stack**: Dashboard UI, API, Event Store, PostgreSQL
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
git clone https://github.com/syntropic137/agentic-engineering-framework.git
cd agentic-engineering-framework

# Initialize submodules
git submodule update --init --recursive

# Install dependencies
uv sync
```

### Step 2: Generate Secrets

```bash
# Generate database password and webhook secret
just secrets-generate

# Verify secrets were created
just secrets-check
```

### Step 3: Copy GitHub App Private Key

Download your GitHub App private key and copy it to the secrets directory:

```bash
cp ~/Downloads/your-app-name.pem infra/docker/secrets/github-private-key.pem

# Verify
just secrets-check
```

### Step 4: Configure Cloudflare Tunnel

#### Option A: Via Cloudflare Dashboard (Recommended)

1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com/)
2. Navigate to **Networks** → **Tunnels** → **Create a tunnel**
3. Name it: `syn-selfhost`
4. Copy the tunnel token to a secret file:

```bash
# Save your tunnel token as a Docker secret
echo "YOUR_TOKEN_HERE" > infra/docker/secrets/cloudflare-tunnel-token.txt
chmod 600 infra/docker/secrets/cloudflare-tunnel-token.txt
```

Add these routes in the tunnel configuration:

| Subdomain | Domain | Service |
|-----------|--------|---------|
| `aef` | yourdomain.com | `http://syn-ui:80` |
| `api.aef` | yourdomain.com | `http://dashboard:8000` |

#### Option B: Via CLI

```bash
# Install cloudflared
brew install cloudflared  # macOS
# or see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create syn-selfhost
cloudflared tunnel route dns syn-selfhost aef.yourdomain.com
cloudflared tunnel route dns syn-selfhost api.aef.yourdomain.com

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
SYN_DOMAIN=aef.yourdomain.com

# GitHub App
SYN_GITHUB_APP_ID=123456
SYN_GITHUB_APP_NAME=your-app-name
SYN_GITHUB_INSTALLATION_ID=12345678
```

> **Note**: The Cloudflare tunnel token is now stored as a Docker secret file
> (`infra/docker/secrets/cloudflare-tunnel-token.txt`), not as an env var.

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
curl https://aef.yourdomain.com/health
curl https://api.aef.yourdomain.com/health
```

## Management Commands

### Daily Operations

```bash
# View all logs
just selfhost-logs

# View specific service logs
just selfhost-logs dashboard
just selfhost-logs cloudflared

# Check health
just health-check

# Restart a service
just selfhost-restart dashboard
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
docker logs ${COMPOSE_PROJECT_NAME:-syntropic137}-dashboard

# Enter container for debugging
docker exec -it ${COMPOSE_PROJECT_NAME:-syntropic137}-dashboard /bin/bash

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
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  cloudflared │───▶│    syn-ui    │───▶│  dashboard   │      │
│  │              │    │   (nginx)    │    │  (FastAPI)   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
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

## Portable Deployment with 1Password (Optional)

Instead of managing plain-text secret files, you can use a 1Password service account
to resolve secrets automatically at startup. This lets you spin up environments
anywhere without copying secret files around.

### Setup

1. Set `OP_VAULT` in `infra/.env`:
   ```bash
   OP_VAULT=syn137-prod
   ```

   Then store the service account token using one of these methods:

   **macOS (recommended)** — store in Keychain (auto-retrieved by selfhost recipes):
   ```bash
   security add-generic-password -U -a "$USER" \
     -s "SYN_OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD" -w "ops_...your-token..."
   ```

   **Linux/CI** — set a vault-specific env var:
   ```bash
   export OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD=ops_...your-token...
   ```

   **Fallback** — set the generic token directly in `infra/.env`:
   ```bash
   OP_SERVICE_ACCOUNT_TOKEN=ops_...your-token...
   ```

2. Set `INCLUDE_OP_CLI=1` in `infra/.env` to include the `op` CLI in the dashboard image.

3. Docker secret files (`db-password.txt`, `redis-password.txt`) are still needed for
   non-Python services (event-store is a Rust binary that doesn't use `op_resolver.py`).
   Store the same password in both 1Password and the secret file, or set
   `POSTGRES_PASSWORD` in `.env` as a simpler alternative.

4. **Graceful fallback**: If 1Password is not configured, everything works with
   `.env` plaintext values and Docker secret files. The `op_resolver.py` module
   silently skips resolution when `OP_SERVICE_ACCOUNT_TOKEN` is unset.

See `docs/development/1password-secrets.md` for full documentation.

## Security Considerations

### Network Security
- **No inbound ports**: All traffic goes through Cloudflare Tunnel
- **Encrypted tunnel**: Connection to Cloudflare is encrypted
- **Service isolation**: Services only accessible within Docker network

### Access Control
- Consider adding [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) for authentication
- Configure Cloudflare WAF rules for additional protection

### Secrets
- Database password stored as Docker secret (not in environment)
- GitHub private key stored as file with restricted permissions
- Rotate secrets periodically: `just secrets-rotate`
- Encrypt secrets for safe storage or version control: `just secrets-seal`
- Decrypt before deployment: `just secrets-unseal`
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

# Verify token file exists
test -s infra/docker/secrets/cloudflare-tunnel-token.txt && echo "Token file OK" || echo "Token file missing or empty"

# Regenerate token in Cloudflare dashboard if needed
```

### Database Connection Issues

```bash
# Check TimescaleDB health
docker exec ${COMPOSE_PROJECT_NAME:-syntropic137}-timescaledb pg_isready -U ${POSTGRES_USER:-syn}

# Check connection from dashboard
docker exec ${COMPOSE_PROJECT_NAME:-syntropic137}-dashboard python -c "import asyncpg; print('OK')"
```

## Next Steps

- Set up [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) for authentication
- Configure alerting (email/Slack) for service failures
- Set up automated backups
- Add monitoring with Prometheus/Grafana
