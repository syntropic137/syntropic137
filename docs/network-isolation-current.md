# Network Isolation Research

**Date:** 2025-12-22
**Context:** Understanding current network isolation implementation

## 🔍 Findings

### Current Configuration

**Settings (workspace.py):**
```python
docker_network: str = Field(
    default="none",  # ← Full network isolation by default!
    description=(
        "Docker network for containers. "
        "Default: none (full network isolation). "
        "Use 'bridge' with allowed_hosts for controlled access."
    ),
)
```

**Security Settings:**
```python
allow_network: bool = Field(
    default=False,  # ← Network disabled by default
    description=(
        "Allow network access from workspaces. "
        "Default: False (full network isolation). "
        "Enable only if agents need to fetch dependencies or make API calls."
    ),
)

allowed_hosts: str = Field(
    default="",  # ← Empty allowlist
    description=(
        "Allowlisted hosts when network is enabled (comma-separated). "
        "Empty = allow all (not recommended). "
        "Example: 'pypi.org,api.github.com'"
    ),
)
```

### Implementation

**DockerIsolationAdapter:**
- Uses `default_network` parameter (defaults to `"syn-network"`)
- Creates Docker network if it doesn't exist
- Containers connect to this network with `--network={network_name}`

**Key Code:**
```python
# Line 79
default_network: str = DEFAULT_NETWORK

# Line 507
f"--network={network_name}",
```

**DEFAULT_NETWORK constant:** Need to find where this is defined.

## ⚠️ Discrepancy Found!

### Settings vs. Implementation

| Layer | Network Setting | Notes |
|-------|----------------|-------|
| **Settings (workspace.py)** | `docker_network = "none"` | Default: full isolation |
| **DockerIsolationAdapter** | `default_network = DEFAULT_NETWORK` | Likely: "syn-network" |
| **Security Policy** | `allow_network = False` | Network disabled |

**Issue:** The settings say `"none"` by default, but the DockerIsolationAdapter uses a named network (`DEFAULT_NETWORK`).

### Questions

1. **What is `DEFAULT_NETWORK`?**
   - Need to find the constant definition
   - Is it "syn-network" or "none"?

2. **Which setting takes precedence?**
   - Does `docker_network` from settings override `default_network` in adapter?
   - Or are they separate configurations?

3. **How does `allow_network=False` relate to Docker network mode?**
   - Is this enforced via egress proxy?
   - Or just documentation?

## 🎯 Practical Reality

### For Claude CLI to Work

Claude CLI needs:
- ✅ Access to `api.anthropic.com` (for LLM API)
- ✅ Access to `github.com` (for gh CLI operations)
- ✅ Access to `pypi.org` (potentially, for pip install)

**Therefore:** Network isolation must allow these hosts, OR agents can't function.

### Current Behavior (Likely)

Based on the code finding GitHub App working:
- Network is probably **NOT** `"none"`
- More likely: `"bridge"` or named network
- Allowlist enforcement: **NOT YET IMPLEMENTED** (ADR-021 mentions this as gap)

## 📋 Next Steps

### Immediate Investigation

1. Find `DEFAULT_NETWORK` constant definition
2. Check how `docker_network` setting is passed to adapter
3. Test actual network behavior:
   ```bash
   docker inspect aef-ws-{container-id} | jq '.[0].NetworkSettings'
   ```

### Integration Test Needed

```python
async def test_network_isolation_config():
    """Verify network configuration matches settings."""
    settings = get_settings()
    
    async with service.create_workspace() as ws:
        # Get actual Docker network mode
        network_info = await ws.inspect_network()
        
        # Should match settings
        expected = settings.workspace.docker_network
        assert network_info["mode"] == expected
        
        # If bridge, test actual connectivity
        if expected == "bridge":
            # Should reach allowed hosts
            result = await ws.execute(["curl", "-I", "https://api.anthropic.com"])
            assert result.exit_code == 0
            
            # Should NOT reach disallowed hosts (if allowlist enforced)
            if settings.workspace_security.allowed_hosts:
                result = await ws.execute(["curl", "-I", "https://evil.com"])
                assert result.exit_code != 0  # Should fail
```

## 🚧 Current State Summary

| Feature | Status | Notes |
|---------|--------|-------|
| **Docker Network** | ⚠️ **Unclear** | Settings say "none", code uses DEFAULT_NETWORK |
| **Network Allowlist** | ❌ **Not Enforced** | Settings exist, but no egress proxy |
| **Claude API Access** | ✅ **Working** | Confirmed by user |
| **GitHub App Access** | ✅ **Working** | Confirmed by user |

**Conclusion:** Network is likely `"bridge"` with NO allowlist enforcement (yet).

## 🔮 Future: Egress Proxy (ADR-021)

From ADR-021:
```
Options:
1. Envoy sidecar: Full-featured but complex
2. mitmproxy: Simple Python-based, good for prototyping
3. iptables + DNS: Lightweight but harder to maintain
4. Cilium/eBPF: Best for Kubernetes at scale
```

This would enable:
- True `--network=none` isolation
- Container connects to proxy via Unix socket
- Proxy enforces allowlist before forwarding

