# Scaling to 10,000 Concurrent Agents

**Goal:** Architecture and implementation plan for 10K concurrent Claude agents

**Current:** ~10-20 agents tested, designed for 1K agents  
**Target:** 10,000 concurrent agents

## 📊 Capacity Planning

### Resource Requirements (10K Agents)

| Component | Per Agent | 10K Agents | Notes |
|-----------|-----------|------------|-------|
| **Memory** | 512MB | 5TB | With Firecracker: 50MB = 500GB |
| **CPU** | 0.5 cores | 5,000 cores | ~100 powerful nodes |
| **Storage** | 1GB workspace | 10TB | Ephemeral, tmpfs |
| **Network** | 10 req/min | 100K req/min | Claude API + GitHub |
| **Cost/hour** | ~$0.10 | ~$1,000 | Local compute |

### Infrastructure Options

#### Option A: Single Powerful Node (Not Viable)
- Max agents per node: ~100-200 (Docker)
- **Conclusion:** Need distributed architecture

#### Option B: Cluster of Nodes (Recommended)
- 100 nodes × 100 agents = 10,000 ✅
- Each node: 32 cores, 128GB RAM
- Firecracker for density: 200 agents/node = 50 nodes

#### Option C: Hybrid (Local + Cloud)
- Local: 5,000 agents (50 Firecracker nodes)
- Cloud overflow (E2B/Modal): 5,000 agents
- Cost: Local $500/hr + Cloud $1,000/hr = $1,500/hr

## 🏗️ Architecture at Scale

### Current (Single Node)

```
┌─────────────────────────────────────────┐
│  Single Host                            │
│                                         │
│  WorkspaceService                       │
│  ├─ Docker containers (10-20 agents)   │
│  ├─ Event collection                   │
│  └─ Network: bridge                    │
└─────────────────────────────────────────┘
```

### Target (Distributed Cluster)

```
┌─────────────────────────────────────────────────────────────────┐
│                      CONTROL PLANE                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Load Balancer│  │ WorkspaceRouter│  │ Redis Cluster       │  │
│  │              │  │ (coordinator)  │  │ (state/locks)       │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  Node 1     │      │  Node 2     │      │  Node 50    │
│             │      │             │      │             │
│ 200 agents  │      │ 200 agents  │      │ 200 agents  │
│ (Firecracker)      │ (Firecracker)      │ (Firecracker)│
│             │      │             │      │             │
│ Shared      │      │ Shared      │      │ Shared      │
│ Egress Proxy│      │ Egress Proxy│      │ Egress Proxy│
└─────────────┘      └─────────────┘      └─────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
                    Shared Services:
                    - Egress Proxy Cluster
                    - TimescaleDB
                    - MinIO (artifacts)
                    - EventStore
```

## 🔥 Critical: Egress Proxy at Scale

### Problem: Per-Agent Proxies Don't Scale

**Current approach (works for <100 agents):**
```
1 agent = 1 proxy container
10,000 agents = 10,000 proxy containers ❌ TOO MUCH!
```

**Memory:** 10K × 50MB = 500GB just for proxies!

### Solution: Shared Proxy Cluster

```
┌─────────────────────────────────────────────────────────────┐
│              Egress Proxy Cluster (Envoy)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Proxy 1  │  │ Proxy 2  │  │ Proxy 3  │  │ Proxy N  │   │
│  │ 2K conns │  │ 2K conns │  │ 2K conns │  │ 2K conns │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│       ▲              ▲              ▲              ▲        │
│       └──────────────┴──────────────┴──────────────┘        │
│                    Load Balancer                            │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   10K agents       10K agents       10K agents
   (all share       (from 50         (proxy pool)
    proxy pool)      nodes)
```

**Key Points:**
- **5-10 Envoy proxies** handle all 10K agents
- Each Envoy: 2,000+ concurrent connections
- Load balanced for HA
- **Memory:** 10 × 500MB = 5GB (vs 500GB!) ✅

### Implementation: Envoy + Service Mesh

```yaml
# Envoy config for shared proxy
static_resources:
  listeners:
  - address:
      socket_address:
        address: 0.0.0.0
        port_value: 8080
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          http_filters:
          # Rate limiting per agent
          - name: envoy.filters.http.ratelimit
            typed_config:
              domain: syn137-agents
              rate_limit_service:
                grpc_service:
                  envoy_grpc:
                    cluster_name: ratelimit
          # Allowlist enforcement
          - name: envoy.filters.http.lua
            typed_config:
              inline_code: |
                function envoy_on_request(request_handle)
                  local host = request_handle:headers():get(":authority")
                  local allowed = {
                    ["api.anthropic.com"] = true,
                    ["github.com"] = true,
                    ["api.github.com"] = true,
                  }
                  if not allowed[host] then
                    request_handle:respond(
                      {[":status"] = "403"},
                      "Host not in allowlist"
                    )
                  end
                end
          - name: envoy.filters.http.router

  clusters:
  - name: anthropic
    connect_timeout: 30s
    type: LOGICAL_DNS
    dns_lookup_family: V4_ONLY
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: anthropic
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: api.anthropic.com
                port_value: 443
    transport_socket:
      name: envoy.transport_sockets.tls
      typed_config:
        "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext
        sni: api.anthropic.com
```

## 🚀 Migration Path to 10K

### Phase 1: Optimize Single Node (Current → 200 agents)

**Timeline:** 1-2 weeks  
**Target:** 200 agents on single node

1. **Switch to Firecracker** (from Docker)
   - Memory: 512MB → 50MB per agent
   - Startup: 2s → 125ms
   - Density: 20 agents → 200 agents per node

2. **Shared egress proxy** (from per-agent)
   - Deploy single Envoy proxy
   - All agents use shared proxy
   - Test with 100+ concurrent agents

3. **Optimize event collection**
   - Batch inserts (already done ✅)
   - Connection pooling to TimescaleDB
   - Async event processing

**Deliverables:**
- Single node handles 200 agents
- Egress proxy tested at scale
- Performance metrics collected

---

### Phase 2: Horizontal Scale (200 → 2,000 agents)

**Timeline:** 2-3 weeks  
**Target:** 2,000 agents across 10 nodes

1. **Distributed WorkspaceRouter**
   ```python
   class DistributedWorkspaceRouter:
       """Route workspace requests across cluster."""
       
       def __init__(self, redis: Redis):
           self.redis = redis
           self.nodes = self._discover_nodes()
       
       async def allocate(self, config: WorkspaceConfig) -> Node:
           """Find node with capacity."""
           for node in self.nodes:
               capacity = await self.redis.get(f"node:{node}:available")
               if int(capacity) > 0:
                   # Reserve capacity atomically
                   await self.redis.decr(f"node:{node}:available")
                   return node
           
           raise NoCapacityError("Cluster at capacity")
   ```

2. **Egress proxy cluster** (HA)
   - Deploy 3 Envoy proxies
   - Load balancer in front
   - Health checks + auto-restart

3. **Centralized state** (Redis)
   - Node registry
   - Capacity tracking
   - Workspace → Node mapping

**Deliverables:**
- 10 nodes in cluster
- 200 agents per node = 2,000 total
- HA proxy cluster
- Redis coordination working

---

### Phase 3: Production Scale (2K → 10K agents)

**Timeline:** 3-4 weeks  
**Target:** 10,000 agents across 50 nodes

1. **Scale to 50 nodes**
   - Automated node provisioning
   - Kubernetes operators (or bare metal automation)
   - Monitoring + alerting per node

2. **Proxy cluster scale-out**
   - 5-10 Envoy proxies
   - Geographic distribution (if needed)
   - Advanced rate limiting

3. **Event collection at scale**
   - Multiple TimescaleDB instances (read replicas)
   - Event queue (Kafka/Redis Streams) if needed
   - Compression + retention policies

4. **Observability at scale**
   - Prometheus + Grafana
   - Distributed tracing (Jaeger)
   - Log aggregation (ELK/Loki)

**Deliverables:**
- 50 nodes operational
- 10,000 concurrent agents tested
- Full observability stack
- Runbooks for operations

---

### Phase 4: Cloud Hybrid (Optional 10K → 20K)

**Timeline:** 2 weeks  
**Target:** Burst to 20K with cloud overflow

1. **E2B/Modal integration**
   - Automatic overflow when local capacity exceeded
   - Cost tracking per source (local vs cloud)

2. **Multi-region** (if global users)
   - Deploy clusters in multiple regions
   - Route users to nearest cluster

**Deliverables:**
- Hybrid local + cloud working
- Cost optimization strategies
- Multi-region deployment (optional)

## 💰 Cost Analysis (10K Agents)

### Hardware (Bare Metal Firecracker)

| Component | Spec | Count | Cost/Month | Notes |
|-----------|------|-------|------------|-------|
| **Compute Nodes** | 32 cores, 128GB RAM | 50 | $25,000 | $500 each |
| **Proxy Cluster** | 8 cores, 32GB RAM | 3 | $1,500 | Envoy proxies |
| **Database** | 16 cores, 64GB RAM | 2 | $2,000 | TimescaleDB HA |
| **Redis Cluster** | 8 cores, 16GB RAM | 3 | $1,500 | Coordination |
| **Network** | 10 Gbps | 50 | $5,000 | Bandwidth |
| **Storage** | 10TB NVMe | - | $2,000 | Artifacts |
| **Total** | | | **$37,000/month** | = $1.23/hour/agent |

### vs Cloud (E2B)

| | Bare Metal | Cloud (E2B) |
|---|------------|-------------|
| **10K agents** | $37K/month | $144K/month |
| **Cost per agent** | $3.70/month | $14.40/month |
| **Savings** | - | **-74%** |

**Conclusion:** Bare metal is 4× cheaper at 10K scale!

## 🎯 Critical Components for 10K

### Must Have ✅

1. **Firecracker** (not Docker)
   - Only way to get 200 agents/node
   - Alternative: Kata Containers (less density)

2. **Shared egress proxy** (Envoy cluster)
   - Per-agent proxies don't scale
   - 5-10 Envoy instances handle all traffic

3. **Distributed coordination** (Redis)
   - Track capacity across nodes
   - Workspace → Node mapping
   - Atomic allocation

4. **Kubernetes or equivalent**
   - Automated node management
   - Health checks + auto-healing
   - Rolling updates

### Nice to Have 📈

5. **Kafka/Redis Streams** (event queue)
   - Decouple event generation from storage
   - Handle burst traffic
   - Not strictly required with TimescaleDB

6. **Service mesh** (Istio/Linkerd)
   - Advanced traffic management
   - Mutual TLS
   - Observability built-in

## 📋 Implementation Priorities

### P0 (Must Do Before 10K)

- [ ] Switch to Firecracker (ADR-021 already designed this)
- [ ] Shared Envoy proxy cluster (not per-agent mitmproxy)
- [ ] Distributed WorkspaceRouter with Redis
- [ ] Kubernetes deployment or equivalent automation
- [ ] Load testing infrastructure (can simulate 10K agents)

### P1 (Important for Production)

- [ ] Monitoring/alerting (Prometheus + Grafana)
- [ ] Distributed tracing (Jaeger)
- [ ] Cost tracking per agent/workflow
- [ ] Automated capacity planning
- [ ] Disaster recovery procedures

### P2 (Optimize Later)

- [ ] Multi-region deployment
- [ ] Cloud hybrid (overflow to E2B)
- [ ] Advanced rate limiting
- [ ] Event queue (Kafka)

## 🚦 Reality Check

### What Changes from Current Implementation

| Component | Current (1-20 agents) | Target (10K agents) | Effort |
|-----------|----------------------|---------------------|--------|
| **Isolation** | Docker | Firecracker | Medium (2 weeks) |
| **Egress proxy** | None or per-agent | Shared Envoy cluster | Medium (2 weeks) |
| **Orchestration** | Single WorkspaceService | Distributed Router + Redis | High (3-4 weeks) |
| **Infrastructure** | Single node | 50-node cluster + K8s | High (4-6 weeks) |
| **Observability** | Dashboard | Prometheus + Grafana + Jaeger | Medium (2 weeks) |

**Total effort:** 3-4 months with 1-2 engineers

### Biggest Challenges

1. **Firecracker migration** - Needs custom init, different from Docker
2. **Kubernetes expertise** - Or equivalent cluster management
3. **Network architecture** - Proxy cluster, load balancing, DNS
4. **Cost** - $37K/month infrastructure + engineering time

## 🎯 Recommendation

### Start Small, Scale Incrementally

1. **Now:** Finish workspace refactor
2. **Month 1:** Optimize to 200 agents/node (Firecracker + shared proxy)
3. **Month 2:** Scale to 2K agents (10 nodes)
4. **Month 3:** Scale to 10K agents (50 nodes)
5. **Month 4:** Production hardening + observability

### Architecture Decision

**Use Envoy, not mitmproxy** for egress proxy:
- mitmproxy: Good for <100 agents
- Envoy: Required for 10K agents (C++ performance)

### Infrastructure Decision

**Kubernetes or equivalent required:**
- 50 nodes is too many to manage manually
- Need automated provisioning, health checks, updates
- K8s is industry standard for this

## 📊 Success Metrics

- [ ] 10,000 agents running concurrently
- [ ] <125ms workspace creation time (Firecracker)
- [ ] <10ms proxy latency per request
- [ ] >99.9% uptime
- [ ] <$5/agent/month infrastructure cost

---

**Bottom Line:** 10K agents is achievable in 3-4 months with proper architecture. The key is Firecracker + shared Envoy proxy + Kubernetes. Current Docker + per-agent proxy won't scale beyond ~100 agents.
