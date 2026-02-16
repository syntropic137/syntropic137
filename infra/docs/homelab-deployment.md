# 🏠 AEF Homelab Deployment Guide

Complete guide for deploying the Agentic Engineering Framework on a homelab server (Mac Mini, Linux box, etc.) with secure external access via Cloudflare Tunnel.

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

### Accounts
- [Cloudflare account](https://dash.cloudflare.com/) with a domain
- [GitHub App](../../../docs/deployment/github-app-setup.md) configured

## Step-by-Step Deployment

### Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/AgentParadise/agentic-engineering-framework.git
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
3. Name it: `aef-homelab`
4. Copy the tunnel token

Add these routes in the tunnel configuration:

| Subdomain | Domain | Service |
|-----------|--------|---------|
| `aef` | yourdomain.com | `http://aef-ui:80` |
| `api.aef` | yourdomain.com | `http://aef-dashboard:8000` |

#### Option B: Via CLI

```bash
# Install cloudflared
brew install cloudflared  # macOS
# or see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create aef-homelab
cloudflared tunnel route dns aef-homelab aef.yourdomain.com
cloudflared tunnel route dns aef-homelab api.aef.yourdomain.com

# Get token
cloudflared tunnel token aef-homelab
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
# Cloudflare Tunnel
CLOUDFLARE_TUNNEL_TOKEN=eyJ...your-token-here
AEF_DOMAIN=aef.yourdomain.com

# GitHub App
AEF_GITHUB_APP_ID=123456
AEF_GITHUB_APP_NAME=your-app-name
AEF_GITHUB_INSTALLATION_ID=12345678
```

### Step 6: Deploy

```bash
# Start the homelab stack
just homelab-up

# This will:
# 1. Build all Docker images
# 2. Start services
# 3. Wait for health checks
# 4. Display status
```

### Step 7: Verify Deployment

```bash
# Check service status
just homelab-status

# Check tunnel status
just homelab-tunnel-status

# Test external access
curl https://aef.yourdomain.com/health
curl https://api.aef.yourdomain.com/health
```

## Management Commands

### Daily Operations

```bash
# View all logs
just homelab-logs

# View specific service logs
just homelab-logs aef-dashboard
just homelab-logs cloudflared

# Check health
just health-check

# Restart a service
just homelab-restart aef-dashboard
```

### Updates

```bash
# Pull latest code
git pull

# Upgrade stack (rebuilds images)
just homelab-upgrade
```

### Troubleshooting

```bash
# Check detailed status
docker ps -a

# View container logs
docker logs aef-dashboard

# Enter container for debugging
docker exec -it aef-dashboard /bin/bash

# Full reset (WARNING: deletes data)
just homelab-reset
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
│                      Your Homelab                               │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  cloudflared │───▶│    aef-ui    │───▶│ aef-dashboard│      │
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
│                    │  PostgreSQL  │◀────────────────────────┘   │
│                    │              │                              │
│                    └──────────────┘                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

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
- Keep Docker images updated: `just homelab-upgrade`
- Monitor Cloudflare security notifications

## Backup & Recovery

### Database Backup

```bash
# Manual backup
docker exec aef-postgres pg_dump -U aef aef > backup-$(date +%Y%m%d).sql

# Restore
cat backup-20250101.sql | docker exec -i aef-postgres psql -U aef aef
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
just homelab-status

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
just homelab-logs
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
just homelab-logs cloudflared

# Verify token
echo $CLOUDFLARE_TUNNEL_TOKEN | head -c 20

# Regenerate token in Cloudflare dashboard if needed
```

### Database Connection Issues

```bash
# Check PostgreSQL health
docker exec aef-postgres pg_isready -U aef

# Check connection from dashboard
docker exec aef-dashboard python -c "import asyncpg; print('OK')"
```

## Next Steps

- Set up [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) for authentication
- Configure alerting (email/Slack) for service failures
- Set up automated backups
- Add monitoring with Prometheus/Grafana
