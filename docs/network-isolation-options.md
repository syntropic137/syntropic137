# Network Isolation Options for Claude Agents

**Context:** Claude CLI needs access to specific APIs (Anthropic, GitHub) to function.

## 🎯 Required Network Access

For Claude CLI to work, agents need:

| Service | URL | Port | Purpose |
|---------|-----|------|---------|
| **Anthropic API** | `api.anthropic.com` | 443 | LLM inference (Claude) |
| **GitHub API** | `api.github.com` | 443 | gh CLI operations |
| **GitHub** | `github.com` | 443 | git clone/push |
| **PyPI** | `pypi.org` | 443 | pip install (optional) |
| **npm** | `registry.npmjs.org` | 443 | npm install (optional) |

## 🔄 Evolution Path

### Phase 1: Current (Working) ✅

**Configuration:** Named Docker network (`syn-workspace-net`)

**Pros:**
- ✅ Works immediately - no config needed
- ✅ Claude API accessible
- ✅ GitHub operations work
- ✅ Simple to implement

**Cons:**
- ⚠️ Allows ALL outbound connections
- ⚠️ No allowlist enforcement
- ⚠️ Not suitable for untrusted agents

**Code:**
```python
DEFAULT_NETWORK = "syn-workspace-net"  # Acts like bridge mode
# Container can reach ANY external host
```

**Best for:** Development, single-tenant, trusted agents

---

### Phase 2: Bridge + Allowlist (Recommended Next) 🎯

**Configuration:** Bridge network with documented allowlist

**Implementation:**
```python
# Settings
docker_network = "bridge"  # or "syn-workspace-net"
allowed_hosts = "api.anthropic.com,github.com,api.github.com,pypi.org"

# Document clearly that enforcement is NOT yet active
# Agents CAN reach other hosts until egress proxy is implemented
```

**Pros:**
- ✅ Documents intended security model
- ✅ Prepares for future enforcement
- ✅ No breaking changes
- ✅ Still works immediately

**Cons:**
- ⚠️ Allowlist not enforced (yet)
- ⚠️ Manual updates needed

**Action items:**
1. Update settings to use `"bridge"` explicitly
2. Document `allowed_hosts` with required APIs
3. Add comment: "Enforcement requires egress proxy (Phase 3)"
4. Update integration tests to verify connectivity

**Best for:** Production (single-tenant), clear security posture

---

### Phase 3: Egress Proxy with Enforcement 🔒

**Configuration:** `--network=none` + Unix socket to proxy

**Architecture:**
```
┌─────────────────┐         ┌─────────────────┐
│  Agent Container│         │  Egress Proxy   │
│  --network=none │◀───────▶│  (mitmproxy)    │◀───▶ Internet
│                 │  Unix   │                 │
│  Can't reach    │  socket │  Enforces:      │
│  internet       │         │  - allowlist    │
│  directly       │         │  - rate limits  │
│                 │         │  - logging      │
└─────────────────┘         └─────────────────┘
```

**Implementation Options:**

#### Option A: mitmproxy (Recommended for Start)
```python
# Simple Python-based proxy
# Good for: Prototyping, single-node deployments

# Start proxy:
mitmproxy --mode transparent --set block_global=false \
  --allow-hosts "api.anthropic.com,github.com,api.github.com"

# Configure container:
docker run \
  --network=none \
  -v /var/run/proxy.sock:/var/run/proxy.sock \
  --env HTTP_PROXY=unix:///var/run/proxy.sock \
  agentic-workspace-claude-cli
```

**Pros:**
- ✅ True network isolation
- ✅ Allowlist enforced
- ✅ Python-based (easy to extend)
- ✅ Good logging/debugging

**Cons:**
- ⚠️ Performance overhead (~10ms/request)
- ⚠️ Additional container per node
- ⚠️ More complex troubleshooting

#### Option B: Envoy Sidecar (Production Grade)
```yaml
# Full-featured L7 proxy
# Good for: Multi-tenant production, K8s deployments

# Envoy config:
static_resources:
  listeners:
  - address: { socket_address: { address: 127.0.0.1, port_value: 8080 } }
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          http_filters:
          - name: envoy.filters.http.ext_authz
            typed_config:
              http_service:
                server_uri:
                  uri: http://token-vending:8080
                  cluster: token_vending
```

**Pros:**
- ✅ Production-grade performance
- ✅ Advanced features (retries, circuit breakers)
- ✅ Can inject auth headers (sidecar pattern from ADR-022)
- ✅ Battle-tested at scale

**Cons:**
- ⚠️ Complex configuration
- ⚠️ Steeper learning curve
- ⚠️ ~50MB memory overhead per container

**Best for:** Multi-tenant production, K8s environments

---

### Phase 4: Zero-Trust Sidecar (ADR-022) 🛡️

**Full implementation of ADR-022** including:
- Envoy sidecar for egress filtering
- Token vending service
- No secrets in container
- Per-request token injection

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│                      Agent Pod                          │
│  ┌───────────────┐          ┌────────────────────┐     │
│  │    Agent      │          │  Envoy Sidecar     │     │
│  │   Container   │─────────▶│  • Token injection │────▶│ Internet
│  │               │          │  • Egress filter   │     │
│  │  NO SECRETS   │          │  • Rate limiting   │     │
│  └───────────────┘          └────────────────────┘     │
│                                      ▲                  │
│                                      │                  │
│                              ┌───────┴────────┐        │
│                              │ Token Vending  │        │
│                              │    Service     │        │
│                              └────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

**When to implement:**
- Offering multi-tenant SaaS
- Hosting untrusted agents
- Compliance requirements
- Need per-request token rotation

**Best for:** Maximum security, untrusted multi-tenant environments

---

## 📊 Decision Matrix

| Use Case | Recommended Phase | Rationale |
|----------|------------------|-----------|
| **Local Dev** | Phase 1 (Current) | Speed > Security |
| **Single-Tenant Prod** | Phase 2 (Bridge + Docs) | Balance security & simplicity |
| **Controlled Multi-Tenant** | Phase 3 (Egress Proxy) | Enforce allowlist |
| **Public SaaS** | Phase 4 (Zero-Trust) | Maximum isolation |

## 🚀 Recommended Next Steps

### Immediate (This Week)

1. **Align settings with implementation:**
   ```python
   # packages/syn-shared/src/syn_shared/settings/workspace.py
   docker_network: str = Field(
       default="syn-workspace-net",  # Change from "none"
       description=(
           "Docker network for containers. "
           "Default: syn-workspace-net (bridge-like, allows all outbound). "
           "For production: implement egress proxy (Phase 3) for allowlist enforcement."
       ),
   )
   ```

2. **Document allowed hosts:**
   ```python
   allowed_hosts: str = Field(
       default="api.anthropic.com,github.com,api.github.com,pypi.org,registry.npmjs.org",
       description=(
           "Required hosts for Claude agents (comma-separated). "
           "NOTE: Allowlist is documented but NOT enforced until egress proxy is implemented. "
           "See ADR-021 for enforcement architecture."
       ),
   )
   ```

3. **Add to AGENTS.md:**
   ```markdown
   ### Network Configuration
   
   **Current:** Bridge mode (`syn-workspace-net`)
   - Agents can reach all external hosts
   - Required: api.anthropic.com, github.com, api.github.com
   - Allowlist documented but not enforced
   
   **Future:** Egress proxy with enforcement (ADR-021)
   - Phase 3: mitmproxy for allowlist enforcement
   - Phase 4: Zero-trust sidecar (ADR-022)
   ```

### Short-Term (Next Sprint)

4. **Create GitHub issue for Phase 3:**
   - Title: "Implement Egress Proxy for Network Allowlist Enforcement"
   - Link to ADR-021
   - Choose: mitmproxy vs Envoy
   - Acceptance criteria: Only allowed hosts reachable

5. **Add network connectivity tests:**
   - Verify required hosts are reachable
   - Document that disallowed hosts are also reachable (until Phase 3)

### Long-Term (When Multi-Tenant)

6. **Implement Phase 4 (ADR-022):**
   - Full sidecar proxy pattern
   - Token vending integration
   - Zero secrets in containers

## 🎯 Bottom Line

**Best approach for GitHub + Anthropic access:**

1. **Now:** Use bridge mode (`syn-workspace-net`) - it works!
2. **Document:** List required hosts in settings
3. **Note:** Allowlist enforcement is future enhancement
4. **Plan:** Egress proxy when you need enforcement (multi-tenant)

No action required immediately - agents work because network is open (by design, for now).
