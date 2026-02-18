# Adding Egress Proxy to Claude CLI Workspace

**Goal:** Add network allowlist enforcement to existing Claude CLI container setup

## 🎯 Quick Summary

**Effort Level:** Medium (4-8 hours for prototype, 1-2 days for production-ready)

**Complexity:** Moderate - mostly infrastructure/config, minimal code changes

## 📋 Current Setup

### What We Have Now

```
┌──────────────────────────────────────┐
│  agentic-workspace-claude-cli        │
│                                      │
│  ┌────────────────────────────────┐  │
│  │  Claude CLI                    │  │
│  │  • Calls api.anthropic.com    │──┼──▶ Internet (ALL hosts)
│  │  • Calls github.com           │  │
│  │  • Can reach ANY host         │  │
│  └────────────────────────────────┘  │
│                                      │
│  Network: syn-workspace-net (bridge) │
└──────────────────────────────────────┘
```

**Dockerfile:**
- Base: `node:22-slim`
- Installs: Claude CLI, Python, git, gh CLI
- Size: ~500MB
- Network: Connected to Docker network (bridge-like)

## 🎯 Target Setup (with Egress Proxy)

### Option A: Separate Proxy Container (Recommended)

```
┌──────────────────┐         ┌─────────────────┐
│  Agent Container │         │  Proxy Container│
│  --network=none  │◀───────▶│  (mitmproxy)    │◀───▶ Internet
│                  │  Custom │                 │      (allowed only)
│  Claude CLI      │  Bridge │  Allowlist:     │
│                  │  Network│  • *.anthropic  │
│                  │         │  • *.github.com │
└──────────────────┘         │  • pypi.org     │
                             └─────────────────┘
```

**Pros:**
- ✅ Clean separation
- ✅ Reusable proxy for multiple agents
- ✅ Easy to debug
- ✅ No changes to agent image

**Cons:**
- ⚠️ Need custom Docker network
- ⚠️ Additional container overhead

### Option B: Proxy Sidecar (Same Pod)

```
┌─────────────────────────────────────────────────────┐
│                    Docker Pod                       │
│  ┌──────────────┐           ┌──────────────────┐   │
│  │  Agent       │  localhost│  Proxy Sidecar   │   │
│  │  Container   │◀──────────▶│  (mitmproxy)     │──▶│ Internet
│  │              │   :8080    │                  │   │
│  └──────────────┘           └──────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Pod-level isolation
- ✅ Kubernetes-compatible
- ✅ Standard pattern

**Cons:**
- ⚠️ Docker Compose doesn't have "pods" natively
- ⚠️ More complex setup

## 🛠️ Implementation Steps

### Phase 1: Prototype with mitmproxy (4-8 hours)

#### Step 1: Create Proxy Container (1 hour)

```dockerfile
# lib/agentic-primitives/providers/workspaces/egress-proxy/Dockerfile
FROM mitmproxy/mitmproxy:latest

# Add allowlist configuration
COPY allowlist.py /config/

# Script to enforce allowlist
ENTRYPOINT ["mitmdump", \
    "--mode", "regular", \
    "--listen-port", "8080", \
    "--scripts", "/config/allowlist.py"]
```

```python
# lib/agentic-primitives/providers/workspaces/egress-proxy/allowlist.py
from mitmproxy import http

ALLOWED_HOSTS = {
    "api.anthropic.com",
    "github.com",
    "api.github.com",
    "pypi.org",
    "registry.npmjs.org",
}

def request(flow: http.HTTPFlow) -> None:
    """Block requests to disallowed hosts."""
    host = flow.request.pretty_host
    
    # Check if host matches allowlist
    allowed = any(
        host == allowed_host or host.endswith(f".{allowed_host}")
        for allowed_host in ALLOWED_HOSTS
    )
    
    if not allowed:
        flow.response = http.Response.make(
            403,  # Forbidden
            f"Host {host} not in allowlist",
            {"Content-Type": "text/plain"}
        )
```

#### Step 2: Add Docker Compose Setup (1 hour)

```yaml
# lib/agentic-primitives/providers/workspaces/claude-cli/docker-compose.egress.yaml
services:
  egress-proxy:
    build: ../egress-proxy
    container_name: syn-egress-proxy
    networks:
      - proxy-net
      - internet
    ports:
      - "8080:8080"  # For debugging
    restart: unless-stopped

  claude-agent:
    build: .
    container_name: aef-claude-agent
    depends_on:
      - egress-proxy
    networks:
      - proxy-net  # Can reach proxy
      # NO internet network!
    environment:
      HTTP_PROXY: "http://egress-proxy:8080"
      HTTPS_PROXY: "http://egress-proxy:8080"
      NO_PROXY: "localhost,127.0.0.1"
    volumes:
      - ./workspace:/workspace

networks:
  proxy-net:
    driver: bridge
  internet:
    driver: bridge
```

#### Step 3: Update Agent Container Config (30 minutes)

No Dockerfile changes needed! Just environment variables:

```bash
# Agent container automatically uses proxy via HTTP_PROXY env var
export HTTP_PROXY=http://egress-proxy:8080
export HTTPS_PROXY=http://egress-proxy:8080

# Claude CLI, curl, npm, pip will all use proxy
claude --print "Hello"
```

#### Step 4: Integration with WorkspaceService (2-3 hours)

```python
# packages/syn-adapters/src/syn_adapters/workspace_backends/docker/docker_isolation_adapter.py

async def _start_egress_proxy(
    self,
    execution_id: str,
) -> str:
    """Start egress proxy container for this execution.
    
    Returns:
        Container ID of proxy
    """
    proxy_name = f"aef-proxy-{execution_id[:8]}"
    
    cmd = [
        "docker", "run", "-d",
        f"--name={proxy_name}",
        "--network=aef-proxy-net",
        "syn-egress-proxy:latest",
    ]
    
    proc = await asyncio.create_subprocess_exec(*cmd, ...)
    await proc.wait()
    
    return proxy_name


async def create(
    self,
    config: IsolationConfig,
) -> IsolationHandle:
    """Create isolated workspace with egress proxy."""
    
    # 1. Start egress proxy
    proxy_container = await self._start_egress_proxy(config.execution_id)
    
    # 2. Start agent container with proxy config
    docker_cmd = self._build_docker_command(
        container_name=container_name,
        workspace_dir=workspace_path,
        network_name="aef-proxy-net",  # Same network as proxy
        config=config,
    )
    
    # Add proxy environment variables
    docker_cmd.extend([
        "-e", f"HTTP_PROXY=http://{proxy_container}:8080",
        "-e", f"HTTPS_PROXY=http://{proxy_container}:8080",
    ])
    
    # 3. Run agent container
    # ...existing code...
```

#### Step 5: Testing (2 hours)

```python
# Test 1: Allowed hosts work
async def test_allowed_hosts():
    async with service.create_workspace() as ws:
        # Should work
        result = await ws.execute(["curl", "https://api.anthropic.com"])
        assert result.exit_code == 0
        
        result = await ws.execute(["curl", "https://github.com"])
        assert result.exit_code == 0

# Test 2: Disallowed hosts blocked
async def test_disallowed_hosts():
    async with service.create_workspace() as ws:
        # Should fail
        result = await ws.execute(["curl", "https://evil.com"])
        assert result.exit_code != 0
        assert "not in allowlist" in result.stderr
```

### Phase 2: Production Hardening (1-2 days)

#### Additional Steps:

1. **Proxy High Availability:**
   - Shared proxy pool instead of per-agent
   - Health checks and auto-restart
   - Load balancing across multiple proxies

2. **Performance Optimization:**
   - Connection pooling
   - HTTP/2 support
   - Caching for repeated requests

3. **Observability:**
   - Log all proxied requests
   - Metrics: requests/sec, blocked requests
   - Alerting on suspicious patterns

4. **Security Hardening:**
   - TLS inspection (if needed)
   - Rate limiting per agent
   - IP allowlist (not just domain)

## 📊 Effort Breakdown

| Task | Complexity | Time | Dependencies |
|------|------------|------|--------------|
| **mitmproxy Dockerfile** | Low | 1h | None |
| **Allowlist script** | Low | 30m | None |
| **Docker Compose setup** | Medium | 1h | Docker knowledge |
| **WorkspaceService integration** | Medium | 2-3h | AEF codebase knowledge |
| **Testing** | Medium | 2h | Test infrastructure |
| **Documentation** | Low | 1h | None |
| **Production hardening** | High | 1-2 days | Performance tuning |

**Total (Prototype):** 4-8 hours  
**Total (Production):** 2-3 days

## 🚦 Difficulty Assessment

### Easy Parts ✅
- mitmproxy is designed for this
- Python script is ~30 lines
- Docker Compose setup is straightforward
- No agent image changes needed

### Medium Parts ⚠️
- WorkspaceService integration (need to understand lifecycle)
- Network configuration (custom Docker networks)
- Testing (need good test coverage)

### Hard Parts ❌
- Performance at scale (100+ concurrent agents)
- Handling edge cases (WebSocket, HTTP/2)
- TLS inspection (if needed for HTTPS)
- Debugging when things go wrong

## 🎯 Recommendation

### For Prototype (Next Sprint)

**Use mitmproxy with separate container:**
```bash
# 1. Build proxy
cd lib/agentic-primitives/providers/workspaces/egress-proxy
docker build -t syn-egress-proxy .

# 2. Start proxy
docker run -d --name proxy --network aef-net syn-egress-proxy

# 3. Start agent with proxy
docker run \
  --network aef-net \
  -e HTTP_PROXY=http://proxy:8080 \
  agentic-workspace-claude-cli
```

**Time:** 1 day for basic working version

### For Production (When Multi-Tenant Needed)

**Consider Envoy instead of mitmproxy:**
- Better performance (C++ vs Python)
- Better observability (metrics, tracing)
- Industry standard
- Steeper learning curve

**Time:** 2-3 days for production-ready

## 🔑 Key Insight

The **agent container needs ZERO changes**! 

Just set `HTTP_PROXY` environment variable and standard tools (curl, npm, pip, Claude CLI) automatically use it.

This makes it very easy to add - it's mostly infrastructure/orchestration work, not code changes.

## 📝 Next Steps

1. ✅ Keep current setup (works fine for single-tenant)
2. 📋 Create GitHub issue for egress proxy implementation
3. ⏭️ Implement when you need multi-tenant
4. 🎯 Start with mitmproxy prototype (1 day)
5. 🚀 Migrate to Envoy for production (if needed)

**Bottom line:** Not hard! Mostly config/infrastructure. The agent container is already proxy-ready.
