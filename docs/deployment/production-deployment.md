# Production Deployment Guide

This guide covers deploying Syn137's isolated workspace architecture in production.
It covers single-server deployments (home lab, bare metal) and scaled deployments.

> **📦 Infrastructure as Code**: For turn-key deployment with Docker Compose and Cloudflare Tunnel, see the [Self-Host Deployment Guide](../../infra/docs/selfhost-deployment.md) in the `infra/` directory. The IaC approach provides:
> - Pre-configured Docker Compose stack with all services
> - Cloudflare Tunnel for secure external access
> - Just recipes for one-command deployment (`just selfhost-up`)
> - Secrets management scripts

## Deployment Options

| Deployment | Scale | Best For |
|------------|-------|----------|
| **Single Server** | 10-100 agents | Home lab, small team |
| **Multi-Server** | 100-1000 agents | Medium teams, CI/CD |
| **Kubernetes** | 1000+ agents | Large scale, cloud |

---

## Single Server Deployment (Home Lab)

Perfect for home labs and small-scale production.

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 4 cores | 16+ cores |
| **RAM** | 8GB | 64GB+ |
| **Storage** | 50GB SSD | 500GB NVMe |
| **Virtualization** | VT-x/AMD-V | Required |

### Setup Steps

#### 1. Prepare the Server

```bash
# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io curl git

# Enable KVM (for Firecracker)
sudo apt install -y qemu-kvm
sudo usermod -aG kvm $USER
sudo usermod -aG docker $USER

# Reboot to apply group changes
sudo reboot
```

#### 2. Install Syn137

```bash
# Clone repository
git clone https://github.com/syntropic137/syntropic137.git
cd syntropic137

# Install with uv
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# Build workspace Docker image
./docker/workspace/build.sh

# (Optional) Setup Firecracker for strongest isolation
./docker/firecracker/setup.sh
```

#### 3. Configure Environment

Create `.env` file:

```bash
# =============================================================================
# Syn137 Production Configuration
# =============================================================================

# ---- Isolation Backend ----
# Options: firecracker (Linux+KVM), gvisor (Docker+runsc), docker_hardened, cloud
SYN_WORKSPACE_ISOLATION_BACKEND=firecracker

# ---- Capacity ----
SYN_WORKSPACE_POOL_SIZE=10              # Pre-warmed workspaces
SYN_WORKSPACE_MAX_CONCURRENT=50         # Maximum concurrent agents

# ---- Cloud Overflow (backup when local capacity exhausted) ----
SYN_WORKSPACE_ENABLE_CLOUD_OVERFLOW=true
SYN_WORKSPACE_CLOUD_PROVIDER=e2b
SYN_WORKSPACE_CLOUD_API_KEY=your-e2b-api-key

# ---- Security Settings ----
SYN_SECURITY_ALLOW_NETWORK=false        # No network by default
SYN_SECURITY_READ_ONLY_ROOT=true        # Read-only root filesystem
SYN_SECURITY_MAX_MEMORY=1Gi             # 1GB per workspace
SYN_SECURITY_MAX_CPU=1.0                # 1 CPU per workspace
SYN_SECURITY_MAX_PIDS=100               # Process limit
SYN_SECURITY_MAX_EXECUTION_TIME=3600    # 1 hour timeout

# ---- Docker Settings ----
SYN_WORKSPACE_DOCKER_IMAGE=syn-workspace:latest
SYN_WORKSPACE_DOCKER_RUNTIME=runsc      # gVisor runtime
SYN_WORKSPACE_DOCKER_NETWORK=none       # No network

# ---- Firecracker Settings (if using Firecracker) ----
SYN_FIRECRACKER_KERNEL_PATH=/var/lib/syn/firecracker/vmlinux
SYN_FIRECRACKER_ROOTFS_PATH=/var/lib/syn/firecracker/rootfs.ext4

# ---- Database ----
SYN_DATABASE_URL=postgresql://syn:password@localhost:5432/syn

# ---- Redis (for coordination) ----
SYN_REDIS_URL=redis://localhost:6379

# ---- Observability ----
SYN_LOG_LEVEL=INFO
SYN_OTEL_ENDPOINT=http://localhost:4317
```

#### 4. Start Services

```bash
# Start supporting services (Postgres, Redis)
docker compose -f docker/docker-compose.dev.yaml up -d

# Start Syn137
npx @syntropic137/cli start
```

#### 5. Verify Installation

```bash
# Check status
npx @syntropic137/cli status

# Run test workflow
npx @syntropic137/cli workflow run examples/hello-world.yaml

# Check workspace isolation
uv run pytest packages/syn-adapters/tests/test_workspace_integration.py -v
```

---

## Multi-Server Deployment

For scaling beyond a single server.

### Architecture

```
                    ┌─────────────────┐
                    │   Load Balancer │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Syn137 Server 1 │    │  Syn137 Server 2 │    │  Syn137 Server 3 │
│               │    │               │    │               │
│ Firecracker   │    │ Firecracker   │    │ Firecracker   │
│ Workspaces    │    │ Workspaces    │    │ Workspaces    │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
               ┌─────────────┴─────────────┐
               ▼                           ▼
        ┌─────────────┐             ┌─────────────┐
        │  PostgreSQL │             │    Redis    │
        │  (primary)  │             │  (cluster)  │
        └─────────────┘             └─────────────┘
```

### Shared State Configuration

All servers must share:

```bash
# Same database
SYN_DATABASE_URL=postgresql://syn:password@db.internal:5432/syn

# Same Redis for coordination
SYN_REDIS_URL=redis://redis.internal:6379

# Same artifact storage
SYN_ARTIFACT_STORAGE_URL=s3://syn-artifacts
```

### Load Balancing

```nginx
# nginx.conf
upstream syn137_servers {
    least_conn;  # Route to least loaded server
    server syn1.internal:8000;
    server syn2.internal:8000;
    server syn3.internal:8000;
}

server {
    listen 443 ssl;
    server_name syn137.example.com;

    location / {
        proxy_pass http://syn137_servers;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket for real-time updates
    location /ws {
        proxy_pass http://syn137_servers;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## Kubernetes Deployment

For maximum scale and cloud-native deployments.

### Prerequisites

- Kubernetes cluster (1.24+)
- Kata Containers or gVisor runtime class
- PersistentVolume storage class

### Helm Chart Installation

```bash
# Add Syn137 Helm repository
helm repo add syn137 https://charts.syn137.dev
helm repo update

# Install with custom values
helm install syn137 syn137/syn137-platform \
    --namespace syn \
    --create-namespace \
    --values values-production.yaml
```

### values-production.yaml

```yaml
# Syn137 Kubernetes Production Values

replicaCount: 3

workspace:
  isolationBackend: kata  # Kata Containers for K8s
  poolSize: 50
  maxConcurrent: 500

  security:
    allowNetwork: false
    readOnlyRoot: true
    maxMemory: "1Gi"
    maxCpu: "1000m"
    maxPids: 100

  # RuntimeClass for Kata Containers
  runtimeClassName: kata

resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
  limits:
    memory: "8Gi"
    cpu: "4000m"

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 20
  targetCPUUtilization: 70

postgresql:
  enabled: true
  auth:
    postgresPassword: "your-secure-password"
  primary:
    persistence:
      size: 100Gi

redis:
  enabled: true
  architecture: replication
  auth:
    password: "your-redis-password"

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: syn137.example.com
      paths:
        - path: /
          pathType: Prefix

monitoring:
  enabled: true
  serviceMonitor:
    enabled: true
```

### Install Kata Containers Runtime

```bash
# Install Kata Containers operator
kubectl apply -f https://raw.githubusercontent.com/kata-containers/kata-containers/main/tools/packaging/kata-deploy/kata-deploy.yaml

# Wait for deployment
kubectl -n kube-system wait --for=condition=ready pod -l name=kata-deploy --timeout=300s

# Create RuntimeClass
cat <<EOF | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
EOF
```

---

## Security Hardening

### Network Policies

```yaml
# Deny all ingress/egress for workspace pods
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-workspace-network
  namespace: syn-workspaces
spec:
  podSelector:
    matchLabels:
      syn137.dev/component: workspace
  policyTypes:
    - Ingress
    - Egress
```

### Pod Security Standards

```yaml
# Enforce restricted security context
apiVersion: v1
kind: Namespace
metadata:
  name: syn-workspaces
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
```

### Secrets Management

```bash
# Use external secrets operator
kubectl apply -f https://charts.external-secrets.io/

# Configure Vault backend
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "https://vault.internal:8200"
      path: "syn"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "syn137-service"
EOF
```

---

## Monitoring & Observability

### Metrics (Prometheus)

```yaml
# ServiceMonitor for Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: syn137-metrics
spec:
  selector:
    matchLabels:
      app: syn
  endpoints:
    - port: metrics
      interval: 15s
```

### Key Metrics to Monitor

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `syn137_workspace_active_count` | Active workspaces | > 80% capacity |
| `syn137_workspace_creation_latency_seconds` | Time to create workspace | > 5s |
| `syn137_workspace_overflow_total` | Cloud overflow count | > 10/hour |
| `syn137_workspace_failed_total` | Failed workspace creations | > 5/hour |
| `syn137_isolation_breach_total` | Security breach attempts | > 0 |

### Dashboards

Import Grafana dashboards:

```bash
# Download Syn137 dashboards
curl -L https://grafana.com/api/dashboards/xxxxx/revisions/1/download \
    -o syn-workspaces.json

# Import to Grafana
curl -X POST http://grafana.internal/api/dashboards/db \
    -H "Content-Type: application/json" \
    -d @syn-workspaces.json
```

---

## Backup & Recovery

### Database Backup

```bash
# Automated backup with pg_dump
pg_dump -h localhost -U syn -d syn | gzip > backup-$(date +%Y%m%d).sql.gz

# Restore
gunzip -c backup-20250101.sql.gz | psql -h localhost -U syn -d syn
```

### Disaster Recovery

1. **RPO (Recovery Point Objective)**: 1 hour
2. **RTO (Recovery Time Objective)**: 15 minutes

```yaml
# Velero backup schedule
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: syn137-daily-backup
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  template:
    includedNamespaces:
      - syn
    ttl: 720h  # 30 days retention
```

---

## Troubleshooting

### Common Issues

#### Workspaces Not Starting

```bash
# Check backend availability
uv run python -c "from syn_adapters.workspaces import WorkspaceRouter; print(WorkspaceRouter().get_available_backends())"

# Check Docker
docker info
docker run --rm hello-world

# Check Firecracker (Linux)
ls -la /dev/kvm
firecracker --version
```

#### High Latency

```bash
# Check pool warmup
uv run python -c "from syn_adapters.workspaces import get_workspace_router; print(get_workspace_router().stats)"

# Increase pool size
export SYN_WORKSPACE_POOL_SIZE=50
```

#### Memory Issues

```bash
# Check container limits
docker stats

# Reduce per-workspace memory
export SYN_SECURITY_MAX_MEMORY=256Mi
```

---

## Maintenance

### Rolling Updates

```bash
# Kubernetes
kubectl rollout restart deployment/syn -n syn

# Docker Compose
docker compose pull && docker compose up -d --no-deps syn
```

### Scaling

```bash
# Scale up
kubectl scale deployment/syn --replicas=5 -n syn

# Horizontal Pod Autoscaler
kubectl autoscale deployment/syn --min=3 --max=20 --cpu-percent=70 -n syn
```

---

## Related Documentation

- [Workspace Architecture README](../../packages/syn-adapters/src/syn_adapters/workspaces/README.md)
- [ADR-021: Isolated Workspace Architecture](../adrs/ADR-021-isolated-workspace-architecture.md)
- [Firecracker Setup](../../docker/firecracker/README.md)
- [Environment Configuration](../env-configuration.md)
