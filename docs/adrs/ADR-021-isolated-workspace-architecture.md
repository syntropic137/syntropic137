# ADR-021: Isolated Workspace Architecture

**Status:** Accepted (Implemented)
**Date:** 2025-12-11
**Deciders:** @neural
**Tags:** security, isolation, workspaces, scale, firecracker, docker

## Context

The Agentic Engineering Framework (AEF) executes coding agents that can:
1. Read and write files
2. Execute shell commands
3. Install packages
4. Make network requests

### Threat Model

Coding agents can be compromised through:

| Attack Vector | Description | Likelihood |
|--------------|-------------|------------|
| Malicious Repository | Agent clones repo containing exploit code | High |
| Prompt Injection | Malicious content in files tricks agent | High |
| Supply Chain | Compromised npm/pip dependencies | Medium |
| LLM Jailbreak | Agent convinced to run harmful commands | Medium |
| Exfiltration | Agent sends secrets to external server | Medium |

**If any attack succeeds, the agent's environment becomes hostile.**

### Scale Requirements

- **Target**: 1,000 concurrent agents
- **Use Case**: Parallel workflow execution, CI/CD pipelines
- **Deployment**: Single powerful server or K8s cluster

### Current State

The existing `LocalWorkspace` uses temporary directories with no isolation:

```python
class LocalWorkspace:
    """File-based workspace in temporary directories."""
    # ❌ No filesystem isolation
    # ❌ No network isolation
    # ❌ No resource limits
    # ❌ Shared kernel with host
```

A compromised agent in `LocalWorkspace` can:
- Read any file the process can access
- Access the network freely
- Consume unlimited resources (DoS)
- Pivot to other agents or host system

## Decision

Implement an **isolation-first workspace architecture** where **all agents run in isolated environments by default**. There is no "trusted" fast path.

### Core Principles

1. **Isolation-First**: Every agent runs isolated—no exceptions
2. **Defense in Depth**: Network + filesystem + resource limits
3. **Tiered Backends**: Multiple isolation technologies for different platforms
4. **Cloud Overflow**: Burst to cloud when local capacity exceeded
5. **Configuration-Driven**: All settings via environment variables

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Workspace Router                              │
│  ALL requests get isolation - tier determines HOW                 │
└─────────────┬────────────────────┬───────────────────────────────┘
              │                    │
      ┌───────▼───────┐    ┌───────▼───────┐
      │   Primary:    │    │   Overflow:   │
      │  Firecracker  │    │  Cloud (E2B)  │
      │   MicroVMs    │    │   Sandboxes   │
      │  500-1000/node│    │   unlimited   │
      └───────┬───────┘    └───────────────┘
              │
    ┌─────────┴─────────┐
    │  Fallback Tiers   │
    │  - Kata Containers│
    │  - gVisor Docker  │
    │  - Hardened Docker│
    └───────────────────┘
```

### Isolation Backend Comparison

| Backend | Kernel Isolation | Filesystem | Network | Scale/Node | Platform |
|---------|------------------|------------|---------|------------|----------|
| Firecracker | ✅ Separate kernel | ✅ Isolated | ✅ None | 500-1000 | Linux+KVM |
| Kata | ✅ Separate kernel | ✅ Isolated | ✅ None | 200-400 | Linux+KVM |
| gVisor | ⚠️ User-space kernel | ✅ Isolated | ✅ None | 50-100 | Linux/macOS |
| Hardened Docker | ❌ Shared kernel | ✅ Isolated | ✅ None | 100-200 | Any |
| E2B/Modal | ✅ Separate kernel | ✅ Isolated | ✅ Configurable | Unlimited | Cloud |

### Backend Selection Logic

```python
def get_default_isolation_backend() -> IsolationBackend:
    """Select best available backend for current platform."""

    if sys.platform == "linux" and Path("/dev/kvm").exists():
        if shutil.which("firecracker"):
            return IsolationBackend.FIRECRACKER
        elif is_kata_available():
            return IsolationBackend.KATA

    if is_gvisor_available():
        return IsolationBackend.GVISOR

    if is_docker_available():
        return IsolationBackend.DOCKER_HARDENED

    raise RuntimeError("No isolation backend available")
```

### Security Configuration

All workspaces enforce these security defaults:

```python
@dataclass
class WorkspaceSecuritySettings:
    """Security settings applied to all isolated workspaces."""

    # Network: Isolated by default
    allow_network: bool = False
    allowed_hosts: list[str] = field(default_factory=list)

    # Filesystem: Read-only root, writable tmpfs
    read_only_root: bool = True
    max_workspace_size: str = "1Gi"

    # Resource limits
    max_memory: str = "512Mi"
    max_cpu: float = 0.5
    max_pids: int = 100
    max_execution_time: int = 3600  # 1 hour
```

### Workspace Router

```python
class WorkspaceRouter:
    """Routes workspace requests to appropriate backend."""

    async def get_workspace(
        self,
        config: WorkspaceConfig,
    ) -> AsyncContextManager[IsolatedWorkspace]:
        """Get an isolated workspace."""

        # Check capacity
        if self.at_capacity():
            if self.settings.enable_cloud_overflow:
                return CloudWorkspace.create(config)
            else:
                await self.wait_for_capacity()

        # Route to configured backend
        backend = self.get_backend(config.isolation_backend)
        return backend.create(config, self.settings.security)
```

### Environment Configuration

```bash
# Backend selection
AEF_WORKSPACE_ISOLATION_BACKEND=firecracker

# Capacity limits
AEF_WORKSPACE_POOL_SIZE=100
AEF_WORKSPACE_MAX_CONCURRENT=1000

# Cloud overflow
AEF_WORKSPACE_ENABLE_CLOUD_OVERFLOW=true
AEF_WORKSPACE_CLOUD_PROVIDER=e2b
AEF_WORKSPACE_CLOUD_API_KEY=sk-...

# Security policies
AEF_SECURITY_ALLOW_NETWORK=false
AEF_SECURITY_MAX_MEMORY=512Mi
AEF_SECURITY_MAX_CPU=0.5
```

## Alternatives Considered

### Alternative 1: Process-Based Isolation (Rejected)

Use cgroups and namespaces without containerization.

```python
class ProcessWorkspace:
    """Lightweight process isolation."""
    # ❌ Rejected: Insufficient isolation for untrusted code
```

**Why Rejected:**
- Shared kernel means kernel exploits can escape
- Complex to implement correctly
- Not suitable for potentially compromised agents

### Alternative 2: Docker Only (Rejected)

Use Docker containers for all workspaces.

**Why Rejected:**
- Container escape CVEs exist (runc vulnerabilities)
- Shared kernel is a weak security boundary
- Not sufficient for truly untrusted code

### Alternative 3: Cloud Only (Rejected)

Use E2B or Modal for all workspaces.

**Why Rejected:**
- Cost prohibitive at scale (1000 agents × $0.20/hour = $200/hour)
- Network latency for every operation
- Vendor dependency for core functionality

### Alternative 4: Trust-Based Tiers (Rejected)

Different isolation levels based on trust:

```python
# ❌ Rejected approach
if workflow.trusted:
    workspace = ProcessWorkspace()  # Fast but unsafe
else:
    workspace = FirecrackerWorkspace()  # Slow but safe
```

**Why Rejected:**
- "Trusted" code can still be compromised (prompt injection)
- Complexity of trust decisions
- Security should be default, not opt-in

## Consequences

### Positive

✅ **Security by Default**: All agents isolated from host and each other

✅ **Compromised Agent Contained**: Attack surface limited to workspace

✅ **Scale-Ready**: Architecture supports 1000+ concurrent agents

✅ **Platform Flexible**: Works on Linux (Firecracker), macOS (gVisor), cloud (E2B)

✅ **Configuration-Driven**: Easy to tune via environment variables

✅ **Cloud Burst**: Overflow to cloud when local capacity exceeded

### Negative

⚠️ **Startup Overhead**: ~125ms (Firecracker) to ~2s (Docker) per workspace

⚠️ **Memory Overhead**: ~50-512MB per isolated workspace

⚠️ **Complexity**: Multiple backends to maintain

⚠️ **Infrastructure Requirements**: KVM for Firecracker, Docker for gVisor

⚠️ **Cloud Costs**: E2B overflow incurs per-second charges

### Mitigations

1. **Startup Overhead**: Pre-warm VM/container pools
2. **Memory Overhead**: Use Firecracker (5MB overhead) over Docker (50MB+)
3. **Complexity**: Abstract behind `WorkspaceProtocol`
4. **Infrastructure**: Auto-detect and fall back to available backends
5. **Cloud Costs**: Configurable overflow limits, cost alerts

## Implementation

See: `PROJECT-PLAN_20251211_ISOLATED-WORKSPACE-ARCHITECTURE.md`

### Milestone Summary

1. **Settings & Configuration**: Add workspace settings to aef-shared
2. **Protocol Extension**: Extend WorkspaceProtocol for isolation
3. **gVisor Backend**: Docker + gVisor for macOS/Linux
4. **Hardened Docker**: Fallback when gVisor unavailable
5. **Firecracker Backend**: MicroVMs for production scale
6. **Cloud Overflow**: E2B integration for burst capacity
7. **Workspace Router**: Intelligent backend selection
8. **Documentation**: ADR, usage guides, runbooks
9. **Testing**: Security tests, scale tests, benchmarks

## Related ADRs

- **ADR-009**: Agentic Execution Architecture (original workspace design)
- **ADR-017**: Scalable Event Collection (multi-environment support)
- **ADR-004**: Environment Configuration (settings pattern)

## References

- [Firecracker Documentation](https://github.com/firecracker-microvm/firecracker)
- [gVisor Documentation](https://gvisor.dev/docs/)
- [Kata Containers](https://katacontainers.io/)
- [E2B Sandboxes](https://e2b.dev/docs)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Container Escape CVEs](https://sysdig.com/blog/container-escape-cve/)
