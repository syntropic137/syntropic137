# AEF Infrastructure

The Syntropic137 (AEF) infrastructure runs as a set of Docker services. This guide gets you from `git clone` to a fully running stack in one command.

## Quickstart

```bash
git clone https://github.com/agentparadise/agentic-engineering-framework.git
cd agentic-engineering-framework
just setup
```

The wizard checks prerequisites, generates secrets, optionally configures your GitHub App, and starts all services. Use `just setup --skip-github` to run without GitHub integration.

## What You'll Get

| Service | Port | URL |
|---------|------|-----|
| Dashboard UI | 80 | http://localhost:80 |
| Dashboard API | 8000 | http://localhost:8000 |
| API Docs | 8000 | http://localhost:8000/docs |
| PostgreSQL | 5432 | `postgresql://aef:***@localhost:5432/aef` |
| Event Store (gRPC) | 50051 | — |
| Collector | 8080 | http://localhost:8080/health |
| MinIO Console | 9001 | http://localhost:9001 |
| MinIO API | 9000 | — |
| Redis | 6379 | — |

## Architecture

```
                    +-----------+
  Browser -------->|  UI (:80) |
                    +-----+-----+
                          |
                    +-----v--------+      +-------------+
                    | Dashboard    |----->| Collector   |
                    | API (:8000)  |      | (:8080)     |
                    +--+-+--+--+---+      +------+------+
                       | |  |  |                 |
          +------------+ |  |  +--------+        |
          |              |  |           |        |
    +-----v----+  +------v--v--+  +-----v---+ +--v-----------+
    | MinIO    |  | PostgreSQL |  | Redis   | | Event Store  |
    | (:9000)  |  | (:5432)    |  | (:6379) | | gRPC (:50051)|
    +----------+  +------------+  +---------+ +--------------+
```

## Manual Setup

If you prefer step-by-step over the wizard:

```bash
# 1. Init submodules
git submodule update --init --recursive

# 2. Generate secrets
just secrets-generate

# 3. (Optional) Copy your GitHub App private key
cp ~/Downloads/your-app.pem infra/docker/secrets/github-private-key.pem

# 4. Configure environment
cp infra/.env.example infra/.env
# Edit infra/.env with your settings

# 5. Start services
just infra-up        # Local (no Cloudflare)
just homelab-up      # Homelab (with Cloudflare Tunnel)

# 6. Seed workflows
just seed-workflows
```

## Management

| Command | Description |
|---------|-------------|
| `just setup` | Interactive setup wizard |
| `just setup-check` | Check prerequisites only |
| `just setup-stage <name>` | Re-run a specific setup stage |
| `just health-check` | Check all service health |
| `just health-wait` | Wait for services to be ready |
| `just infra-up` | Start local infrastructure |
| `just infra-down` | Stop local infrastructure |
| `just infra-logs` | Follow service logs |
| `just homelab-up` | Start with Cloudflare Tunnel |
| `just homelab-status` | Show container status |
| `just secrets-generate` | Generate deployment secrets |
| `just secrets-check` | Verify secrets exist |
| `just seed-workflows` | Seed workflow definitions |

## Directory Structure

```
infra/
├── .env.example          # Environment configuration template
├── docker/
│   ├── compose/          # Docker Compose files
│   │   ├── docker-compose.yaml         # Production base
│   │   ├── docker-compose.homelab.yaml # Homelab overrides
│   │   └── docker-compose.dev.yaml     # Dev overrides (in repo root)
│   ├── images/           # Dockerfiles
│   └── secrets/          # Docker secrets (gitignored)
├── cloudflare/           # Cloudflare Tunnel configuration
├── scripts/              # Setup and management scripts
│   ├── setup.py          # Interactive setup wizard
│   ├── secrets_setup.py  # Secrets management
│   └── health_check.py   # Health check utility
└── docs/                 # Deployment documentation
```

## Troubleshooting

**Port already in use**
Check what's using the port before killing it (Docker may own it):
```bash
lsof -i :8000    # Check who owns the port
just setup-check # See all port conflicts
```

**Services unhealthy after startup**
Services may need a minute to initialize. Wait and retry:
```bash
just health-wait 180    # Wait up to 3 minutes
just infra-logs         # Check logs for errors
```

**Submodule errors**
If builds fail with missing files, re-init submodules:
```bash
git submodule update --init --recursive
```

**MinIO buckets not created**
The `minio-init` sidecar creates buckets on first start. If it failed:
```bash
docker compose -f infra/docker/compose/docker-compose.yaml restart minio-init
```

**Stale Docker state**
Nuclear option — removes all containers and volumes (DATA LOSS):
```bash
just homelab-reset   # Or: just dev-reset for dev stack
```

## Further Reading

- [Homelab Deployment Guide](docs/homelab-deployment.md)
- [Secrets Management](docs/secrets-management.md)
- [Cloudflare Tunnel Setup](cloudflare/README.md)
- [Troubleshooting](docs/troubleshooting.md)
