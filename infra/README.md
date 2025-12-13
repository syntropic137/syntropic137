# 🏗️ AEF Infrastructure

Infrastructure as Code for deploying the Agentic Engineering Framework.

## Directory Structure

```
infra/
├── .env.example          # Environment configuration template
├── docker/
│   ├── compose/          # Docker Compose files
│   │   ├── docker-compose.yaml         # Production base stack
│   │   ├── docker-compose.dev.yaml     # Development overrides
│   │   └── docker-compose.homelab.yaml # Homelab + Cloudflare Tunnel
│   ├── images/           # Dockerfiles
│   │   ├── aef-dashboard/
│   │   └── aef-ui/
│   └── secrets/          # Docker secrets (gitignored)
├── cloudflare/           # Cloudflare Tunnel configuration
├── scripts/              # Deployment scripts (Python)
└── docs/                 # Deployment documentation
```

## Quick Start

### Local Development

```bash
# Start infrastructure stack
just infra-up

# Check status
just infra-status

# View logs
just infra-logs
```

### Homelab Deployment

```bash
# 1. Generate secrets
just secrets-generate

# 2. Copy your GitHub App private key
cp ~/Downloads/your-app.pem infra/docker/secrets/github-private-key.pem

# 3. Configure environment
cp infra/.env.example infra/.env
# Edit infra/.env with your Cloudflare settings

# 4. Start with Cloudflare Tunnel
just homelab-up

# 5. Check tunnel status
just homelab-tunnel-status
```

## Environment Files

| File | Purpose |
|------|---------|
| `.env.example` | Template with all variables documented |
| `.env` | Your local configuration (gitignored) |

## Secrets Management

Secrets are stored as files in `docker/secrets/` (gitignored):

| Secret | File | How to Generate |
|--------|------|-----------------|
| DB Password | `db-password.txt` | `just secrets-generate` |
| GitHub Webhook | `github-webhook-secret.txt` | `just secrets-generate` |
| GitHub Private Key | `github-private-key.pem` | Copy from GitHub App settings |

## Documentation

- [Homelab Deployment Guide](docs/homelab-deployment.md)
- [Secrets Management](docs/secrets-management.md)
- [Cloudflare Tunnel Setup](cloudflare/README.md)
- [Troubleshooting](docs/troubleshooting.md)
