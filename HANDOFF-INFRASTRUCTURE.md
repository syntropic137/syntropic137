# 🏗️ Handoff: Infrastructure as Code (Track 4)

**Branch:** `feat/infrastructure`
**Worktree:** `worktrees/infrastructure`
**Priority:** P2
**Project Plan:** [PROJECT-PLAN_20251211_INFRASTRUCTURE-AS-CODE.md](PROJECT-PLAN_20251211_INFRASTRUCTURE-AS-CODE.md)

---

## TL;DR

Implement **Infrastructure as Code (IaC)** for idempotent deployments across homelab (Mac Mini) and cloud environments. Enables reproducible, version-controlled infrastructure with Docker Compose, Terraform, and Cloudflare Tunnel integration.

**Cross-Platform:** All automation uses `just` recipes and Python scripts - **no `.sh` files**. Works on Windows, Linux, and macOS.

---

## Quick Start

```bash
# Create worktree
cd /path/to/agentic-engineering-framework
git worktree add worktrees/infrastructure -b feat/infrastructure

cd worktrees/infrastructure
```

---

## Pre-Requisite: Test GitHub App Locally

Before IaC deployment, verify GitHub App works:

```bash
# Set environment variables
export AEF_GITHUB_APP_ID=your-app-id
export AEF_GITHUB_APP_NAME=aef-engineer-beta
export AEF_GITHUB_PRIVATE_KEY="$(cat /path/to/private-key.pem)"
export AEF_GITHUB_INSTALLATION_ID=your-installation-id

# Test in Python
cd /path/to/agentic-engineering-framework
uv run python -c "
from aef_shared.settings import get_settings
settings = get_settings()
github = settings.github
print(f'Configured: {github.is_configured}')
print(f'Bot name: {github.bot_username}')
print(f'Bot email: {github.bot_email}')
"
```

Expected output:
```
Configured: True
Bot name: aef-engineer-beta[bot]
Bot email: 123456+aef-engineer-beta[bot]@users.noreply.github.com
```

---

## Why IaC?

| Approach | Reproducibility | Version Control | Multi-Env | Rollback |
|----------|-----------------|-----------------|-----------|----------|
| Manual Setup | ❌ Error-prone | ❌ No history | ❌ Drift | ❌ Manual |
| **IaC** | **✅ Idempotent** | **✅ Git tracked** | **✅ Parameterized** | **✅ Automated** |

---

## Target Environments

| Environment | Runtime | Networking | Secrets | Use Case |
|-------------|---------|------------|---------|----------|
| **Local Dev** | Docker Compose | localhost | `.env` file | Development |
| **Homelab** | Docker Compose | Cloudflare Tunnel | Docker Secrets | Beta testing |
| **Cloud (AWS)** | ECS/Fargate | ALB + VPC | Secrets Manager | Production |
| **Cloud (GCP)** | Cloud Run | Load Balancer | Secret Manager | Alternative |

---

## Directory Structure

```
infra-as-code/
├── docker/                          # Docker configurations
│   ├── compose/
│   │   ├── docker-compose.yaml      # Full production stack
│   │   ├── docker-compose.dev.yaml  # Development overrides
│   │   ├── docker-compose.homelab.yaml # Homelab with Cloudflare
│   │   └── .env.example
│   ├── images/
│   │   ├── aef-dashboard/
│   │   │   └── Dockerfile
│   │   ├── aef-worker/
│   │   │   └── Dockerfile
│   │   └── workspace/               # Existing isolated workspace
│   │       └── Dockerfile
│   └── scripts/
│       ├── deploy.py              # Cross-platform (Python)
│       ├── health_check.py
│       └── secrets_setup.py
│
├── terraform/                       # Cloud infrastructure
│   ├── modules/
│   │   ├── networking/              # VPC, subnets, security groups
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── database/                # RDS/Cloud SQL
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── compute/                 # ECS/Cloud Run
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── secrets/                 # Secrets management
│   │   │   ├── main.tf
│   │   │   └── variables.tf
│   │   └── cloudflare/              # Tunnel + DNS
│   │       ├── main.tf
│   │       └── variables.tf
│   └── envs/
│       ├── homelab/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   ├── terraform.tfvars.example
│       │   └── backend.tf
│       ├── staging/
│       │   └── ...
│       └── prod/
│           └── ...
│
├── cloudflare/                      # Cloudflare Tunnel configs
│   ├── tunnel-config.yaml.example
│   └── README.md
│
└── docs/
    ├── deployment-guide.md
    ├── secrets-management.md
    └── troubleshooting.md
```

---

## Docker Compose Stack

### Services

```yaml
# docker-compose.yaml
services:
  # Core Services
  aef-dashboard:
    build: ./images/aef-dashboard
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://aef:${DB_PASSWORD}@postgres:5432/aef
      - AEF_GITHUB_APP_ID=${GITHUB_APP_ID}
      - AEF_GITHUB_PRIVATE_KEY_FILE=/run/secrets/github_private_key
      - AEF_GITHUB_INSTALLATION_ID=${GITHUB_INSTALLATION_ID}
      - AEF_GITHUB_WEBHOOK_SECRET_FILE=/run/secrets/github_webhook_secret
    secrets:
      - github_private_key
      - github_webhook_secret
    depends_on:
      - postgres
      - event-store

  # Database
  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=aef
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
      - POSTGRES_DB=aef
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-db:/docker-entrypoint-initdb.d
    secrets:
      - db_password

  # Event Store
  event-store:
    image: ghcr.io/agentparadise/event-store:latest
    ports:
      - "50051:50051"
    environment:
      - DATABASE_URL=postgresql://events:${EVENTS_DB_PASSWORD}@postgres:5432/events
    depends_on:
      - postgres

  # UI (Development)
  aef-ui:
    build: ./images/aef-ui
    ports:
      - "5173:5173"
    depends_on:
      - aef-dashboard

  # Cloudflare Tunnel (Homelab only)
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    profiles:
      - homelab

secrets:
  github_private_key:
    file: ./secrets/github-private-key.pem
  github_webhook_secret:
    file: ./secrets/github-webhook-secret.txt
  db_password:
    file: ./secrets/db-password.txt

volumes:
  postgres_data:
```

### Environment-Specific Overrides

```yaml
# docker-compose.homelab.yaml
services:
  cloudflared:
    profiles: []  # Enable in homelab

  aef-dashboard:
    restart: always
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## Terraform Modules

### Cloudflare Tunnel (Homelab)

```hcl
# terraform/modules/cloudflare/main.tf
resource "cloudflare_tunnel" "aef" {
  account_id = var.cloudflare_account_id
  name       = "aef-${var.environment}"
  secret     = random_password.tunnel_secret.result
}

resource "cloudflare_tunnel_config" "aef" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_tunnel.aef.id

  config {
    ingress_rule {
      hostname = "aef.${var.domain}"
      service  = "http://aef-dashboard:8000"
    }
    ingress_rule {
      service = "http_status:404"
    }
  }
}

resource "cloudflare_record" "aef" {
  zone_id = var.cloudflare_zone_id
  name    = "aef"
  value   = cloudflare_tunnel.aef.cname
  type    = "CNAME"
  proxied = true
}
```

### AWS ECS (Production)

```hcl
# terraform/modules/compute/main.tf
resource "aws_ecs_cluster" "aef" {
  name = "aef-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_service" "dashboard" {
  name            = "aef-dashboard"
  cluster         = aws_ecs_cluster.aef.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = var.dashboard_replicas
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.dashboard.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "dashboard"
    container_port   = 8000
  }
}
```

---

## Secrets Management

### Local/Homelab

```bash
# Create secrets directory (gitignored)
mkdir -p infra-as-code/docker/secrets

# Generate secrets
openssl rand -hex 32 > infra-as-code/docker/secrets/db-password.txt
openssl rand -hex 32 > infra-as-code/docker/secrets/github-webhook-secret.txt

# Copy GitHub App private key
cp ~/Downloads/aef-app.pem infra-as-code/docker/secrets/github-private-key.pem
```

### Cloud (AWS)

```hcl
resource "aws_secretsmanager_secret" "github_private_key" {
  name = "aef/${var.environment}/github-private-key"
}

resource "aws_secretsmanager_secret_version" "github_private_key" {
  secret_id     = aws_secretsmanager_secret.github_private_key.id
  secret_string = var.github_private_key
}
```

---

## Deployment Commands

### Local Development

```bash
# Start full stack
cd infra-as-code/docker/compose
docker compose up -d

# View logs
docker compose logs -f aef-dashboard

# Rebuild after code changes
docker compose build aef-dashboard
docker compose up -d aef-dashboard
```

### Homelab (Mac Mini)

```bash
# Start with Cloudflare tunnel
docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml up -d

# Check tunnel status
docker compose logs cloudflared
```

### Cloud (Terraform)

```bash
# Initialize
cd infra-as-code/terraform/envs/prod
terraform init

# Plan
terraform plan -var-file=terraform.tfvars

# Apply
terraform apply -var-file=terraform.tfvars

# Destroy (careful!)
terraform destroy -var-file=terraform.tfvars
```

---

## Milestones

### Phase 1: Docker Foundation
- [ ] **M4.1** Create `infra-as-code/` directory structure + justfile
- [ ] **M4.2** Production `docker-compose.yaml` with all services
- [ ] **M4.3** Dashboard Dockerfile (multi-stage build)
- [ ] **M4.4** Secrets management (Python scripts, Docker secrets)
- [ ] **M4.5** Health check (Python script, cross-platform)

### Phase 2: Homelab Deployment
- [ ] **M4.6** Cloudflare Tunnel integration
- [ ] **M4.7** `docker-compose.homelab.yaml` overrides
- [ ] **M4.8** Terraform module for Cloudflare Tunnel
- [ ] **M4.9** Deployment documentation
- [ ] **M4.10** Backup/restore (Python scripts + just recipes)

### Phase 3: Cloud Infrastructure
- [ ] **M4.11** Terraform networking module (VPC, subnets)
- [ ] **M4.12** Terraform database module (RDS)
- [ ] **M4.13** Terraform compute module (ECS/Fargate)
- [ ] **M4.14** Terraform secrets module (Secrets Manager)
- [ ] **M4.15** CI/CD pipeline (GitHub Actions)

### Phase 4: Observability
- [ ] **M4.16** Centralized logging (CloudWatch/Loki)
- [ ] **M4.17** Metrics collection (Prometheus/CloudWatch)
- [ ] **M4.18** Alerting setup
- [ ] **M4.19** Dashboard (Grafana)

---

## Existing Resources

### Current Docker Setup
- `docker/docker-compose.dev.yaml` - Existing dev compose
- `docker/workspace/Dockerfile` - Isolated workspace container
- `docker/egress-proxy/` - Network security proxy
- `docker/init-db/` - Database initialization

### Event Store Platform
- `lib/event-sourcing-platform/infra-as-code/` - Existing Terraform modules
  - AWS production modules
  - Proxmox homelab modules

---

## Environment Variables

| Variable | Required | Description | Where to Get |
|----------|----------|-------------|--------------|
| `DB_PASSWORD` | Yes | PostgreSQL password | Generate with `openssl rand -hex 32` |
| `EVENTS_DB_PASSWORD` | Yes | Event store DB password | Generate |
| `GITHUB_APP_ID` | Yes | GitHub App ID | GitHub App settings |
| `GITHUB_INSTALLATION_ID` | Yes | Installation ID | Installation URL |
| `CLOUDFLARE_TUNNEL_TOKEN` | Homelab | Tunnel token | Cloudflare dashboard |
| `CLOUDFLARE_ACCOUNT_ID` | Homelab | Account ID | Cloudflare dashboard |

---

## Security Considerations

1. **Never commit secrets** - Use `.gitignore` for secrets/
2. **Use Docker secrets** - Not environment variables for sensitive data
3. **Rotate credentials** - GitHub private key every 90 days
4. **Network isolation** - Private subnets for databases
5. **HTTPS only** - Cloudflare handles TLS termination
6. **Least privilege** - Minimal IAM roles for cloud resources

---

## Related Documentation

- [GitHub App Setup Guide](docs/deployment/github-app-setup.md)
- [Environment Configuration](docs/env-configuration.md)
- [ADR-021: Isolated Workspace Architecture](docs/adrs/ADR-021-isolated-workspace-architecture.md)

---

## RIPER Mode

```
ENTER PLAN MODE
```

Review and refine this plan before execution.
