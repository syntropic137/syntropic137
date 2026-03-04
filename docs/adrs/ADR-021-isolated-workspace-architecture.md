# ADR-021: Isolated Workspace Architecture

**Status:** Accepted (Implemented, Enforcement in ADR-023)
**Date:** 2025-12-11
**Updated:** 2026-02-18 — Hook event transport: `stderr=STDOUT` required in stream() (see Hook Event Transport section)
**Deciders:** @neural
**Tags:** security, isolation, workspaces, scale, firecracker, docker, observability, hooks

> **Enforcement Note:** This ADR defines the isolation architecture. The **enforcement mechanisms**
> (how the executor requires isolation and fails without it) are specified in
> **[ADR-023: Workspace-First Execution Model](./ADR-023-workspace-first-execution-model.md)**.
>
> Key enforcement rules from ADR-023:
> - `LocalWorkspace` raises `RuntimeError` in non-test environments
> - `WorkflowExecutionEngine` requires `WorkspaceRouter` as a dependency
> - `WorkspaceRouter` fails if no backend is available in production

## Context

The Syntropic137 executes coding agents that can:
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
SYN_WORKSPACE_ISOLATION_BACKEND=firecracker

# Capacity limits
SYN_WORKSPACE_POOL_SIZE=100
SYN_WORKSPACE_MAX_CONCURRENT=1000

# Cloud overflow
SYN_WORKSPACE_ENABLE_CLOUD_OVERFLOW=true
SYN_WORKSPACE_CLOUD_PROVIDER=e2b
SYN_WORKSPACE_CLOUD_API_KEY=sk-...

# Security policies
SYN_SECURITY_ALLOW_NETWORK=false
SYN_SECURITY_MAX_MEMORY=512Mi
SYN_SECURITY_MAX_CPU=0.5
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

1. **Settings & Configuration**: Add workspace settings to syn-shared
2. **Protocol Extension**: Extend WorkspaceProtocol for isolation
3. **gVisor Backend**: Docker + gVisor for macOS/Linux
4. **Hardened Docker**: Fallback when gVisor unavailable
5. **Firecracker Backend**: MicroVMs for production scale
6. **Cloud Overflow**: E2B integration for burst capacity
7. **Workspace Router**: Intelligent backend selection
8. **Documentation**: ADR, usage guides, runbooks
9. **Testing**: Security tests, scale tests, benchmarks

## POC Findings (2025-12-11)

Proof-of-concept testing validated the isolated workspace architecture:

### Test Results

| Test | Status | Duration | Notes |
|------|--------|----------|-------|
| Network isolation (`--network=none`) | ✅ PASS | <100ms | All external access blocked |
| Network bridge (`--network=bridge`) | ✅ PASS | <100ms | Can reach external services |
| GitHub clone in container | ✅ PASS | ~15s | Cloned `octocat/Hello-World` successfully |
| Claude SDK installation | ✅ PASS | ~8s | `pip install anthropic` works |
| Package manager (apt-get) | ✅ PASS | ~10s | Can install git, curl, etc. |

### Key Findings

1. **Network Isolation Works**
   - `--network=none` completely blocks all network access
   - Agents cannot exfiltrate data when network is disabled

2. **Network Access Required for Coding Agents**
   - Claude API (`api.anthropic.com`) - for agent execution
   - GitHub (`github.com`, `api.github.com`) - for repo cloning
   - Package registries (`pypi.org`, `registry.npmjs.org`) - for dependencies

3. **Allowlist Not Yet Enforced**
   - Current implementation uses `--network=bridge` which allows ALL hosts
   - **GAP**: Need egress proxy or iptables rules to enforce allowlist

### Performance Benchmarks

```
Backend: docker_hardened (macOS)
┏━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Metric       ┃  Mean ┃   P95 ┃   P99 ┃
┡━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ Create Time  │ 179ms │ 215ms │ 216ms │
│ Destroy Time │ 5.53s │ 5.80s │ 5.85s │
│ Parallel 10x │ 9.54x │   -   │   -   │ ← Near-linear scaling
└──────────────┴───────┴───────┴───────┘
```

## Integration Gaps

The following gaps must be closed for production readiness:

### Critical (P0)

| Gap | Current State | Required State | Effort |
|-----|---------------|----------------|--------|
| **Git Identity Configuration** | No git config → agent cannot commit | Inject user.name/user.email + credentials | Medium |
| **Egress Filtering** | `--network=bridge` allows all hosts | Allowlist-only egress via proxy | Medium |
| **API Key Injection** | Not implemented | Secure injection of ANTHROPIC_API_KEY | Small |
| **Agent Executor Integration** | Uses `LocalWorkspace` | Use `WorkspaceRouter` | Medium |
| **Dashboard Workspace Events** | Not shown in UI | Display workspace ID, backend, status | Medium |

### High (P1)

| Gap | Current State | Required State | Effort |
|-----|---------------|----------------|--------|
| **Pre-warmed Container Pool** | Containers created on-demand | Pool of ready containers | Large |
| **Artifact Collection** | Basic file copy | Structured artifact extraction | Medium |
| **Session ↔ Workspace Linkage** | Events separate | Unified session context | Small |

### Medium (P2)

| Gap | Current State | Required State | Effort |
|-----|---------------|----------------|--------|
| **Firecracker Production** | Scripts only | Automated kernel/rootfs management | Large |
| **Container Resource Monitoring** | None | Real-time CPU/memory metrics | Medium |
| **Workspace Timeout Enforcement** | None | Hard kill after max_execution_time | Small |

## Architecture: Agent Inside Container

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Syn137 Control Plane (Host)                          │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────┐                  │
│  │ Dashboard   │◀──▶│ Workflow     │◀──▶│ Event Store    │                  │
│  │ (UI)        │    │ Orchestrator │    │ (PostgreSQL)   │                  │
│  └─────────────┘    └──────┬───────┘    └────────────────┘                  │
│                            │                                                 │
│                   ┌────────▼────────┐                                        │
│                   │ WorkspaceRouter │                                        │
│                   └────────┬────────┘                                        │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │ docker exec / VM socket
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Isolated Container / MicroVM                             │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Claude Agent SDK                                 │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │ LLM Calls   │  │ Tool Calls  │  │ Hooks       │                  │   │
│  │  │ (Anthropic) │  │ (Read/Write)│  │ (Validators)│                  │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │   │
│  │         │                │                │                          │   │
│  │         ▼                ▼                ▼                          │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │                    /workspace                                │    │   │
│  │  │  ├── .context/    (injected prompt, config)                  │    │   │
│  │  │  ├── .claude/     (hooks, handlers)                          │    │   │
│  │  │  ├── repo/        (cloned GitHub repository)                 │    │   │
│  │  │  └── output/      (artifacts to collect)                     │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Network: bridge (egress proxy) → api.anthropic.com, github.com only       │
│  Filesystem: tmpfs with size limit                                          │
│  Resources: --memory=512m --cpus=0.5 --pids-limit=100                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Egress Proxy Design (TODO)

To enforce the network allowlist, an egress proxy sidecar is needed:

```
┌─────────────────────┐         ┌─────────────────────┐
│  Agent Container    │         │  Egress Proxy       │
│                     │         │  (Envoy/mitmproxy)  │
│  --network=none     │◀───────▶│                     │◀───▶ Internet
│  BUT: connected to  │  unix   │  Allowlist:         │
│  proxy network      │  socket │  - api.anthropic.com│
│                     │         │  - github.com       │
└─────────────────────┘         │  - pypi.org         │
                                └─────────────────────┘
```

Options:
1. **Envoy sidecar**: Full-featured but complex
2. **mitmproxy**: Simple Python-based, good for prototyping
3. **iptables + DNS**: Lightweight but harder to maintain
4. **Cilium/eBPF**: Best for Kubernetes at scale

## Git Identity & Credentials (P0 Gap)

### Problem

Fresh containers have **no git configuration**:

```bash
$ docker run python:3.12-slim git commit -m "test"
Author identity unknown

*** Please tell me who you are.

fatal: unable to auto-detect email address
```

Agents cannot commit code without:
1. `git config user.name`
2. `git config user.email`
3. Git credentials for pushing (SSH key or token)

### Solution Design

#### 1. Git Identity Configuration

Inject git identity when creating workspace:

```python
# In WorkspaceRouter.create()
await router.execute_command(
    workspace,
    ["git", "config", "--global", "user.name", git_config.name]
)
await router.execute_command(
    workspace,
    ["git", "config", "--global", "user.email", git_config.email]
)
```

**Identity Sources** (in priority order):

| Environment | Identity | Committer |
|-------------|----------|-----------|
| **Local Development** | User's `.gitconfig` | `NeuralEmpowerment <neuralempowerment@gmail.com>` |
| **CI/CD** | Bot account | `syn-bot[bot] <bot@syn137.dev>` |
| **Production** | GitHub App | `syn-app[bot] <123456+syn-app[bot]@users.noreply.github.com>` |

**Configuration:**

```bash
# User identity (local)
export SYN_GIT_USER_NAME="NeuralEmpowerment"
export SYN_GIT_USER_EMAIL="neuralempowerment@gmail.com"

# Bot identity (production)
export SYN_GIT_USER_NAME="syn-bot[bot]"
export SYN_GIT_USER_EMAIL="bot@syn137.dev"
```

#### 2. Git Credentials Injection

**For HTTPS (recommended):**

```python
# Inject GitHub token
await router.execute_command(
    workspace,
    ["git", "config", "--global", "credential.helper", "store"]
)

# Create .git-credentials file
credentials = f"https://{token}:x-oauth-basic@github.com\n"
await router.execute_command(
    workspace,
    ["sh", "-c", f"echo '{credentials}' > ~/.git-credentials && chmod 600 ~/.git-credentials"]
)
```

**For SSH (more secure but complex):**

```python
# Inject SSH key
ssh_key = os.environ["SYN_GIT_SSH_KEY"]  # Base64 encoded
await router.execute_command(
    workspace,
    ["sh", "-c", f"mkdir -p ~/.ssh && echo '{ssh_key}' | base64 -d > ~/.ssh/id_ed25519 && chmod 600 ~/.ssh/id_ed25519"]
)
```

#### 3. GitHub App Integration (Production)

For production, use a **GitHub App** instead of personal tokens:

```python
@dataclass
class GitHubAppConfig:
    app_id: str
    installation_id: str
    private_key: str  # PEM format

    def get_installation_token(self) -> str:
        """Get short-lived token from GitHub App."""
        # Generate JWT, exchange for installation token
        # Token expires in 1 hour (safer than long-lived tokens)
```

**Benefits:**
- ✅ Fine-grained permissions (only repos the app is installed on)
- ✅ Tokens expire automatically (1 hour)
- ✅ Audit trail (commits show as `app[bot]`)
- ✅ No user impersonation

**Example commit:**

```
commit abc123
Author: syn-app[bot] <123456+syn-app[bot]@users.noreply.github.com>
Date:   Wed Dec 11 19:30:00 2025

    feat: implement code review suggestions

    Applied by Syn137 agent in workflow execution #456
```

#### 4. Commit Metadata & Traceability

All agent commits should include:

```python
commit_message = f"""feat: {user_provided_summary}

Applied by Syn137 agent
- Workflow: {workflow_id}
- Execution: {execution_id}
- Session: {session_id}
- Agent: {agent_name}
- Timestamp: {datetime.now(UTC).isoformat()}

Co-authored-by: {original_user_name} <{original_user_email}>
"""
```

This provides:
- ✅ Full audit trail
- ✅ Links back to workflow execution
- ✅ Credit to human who initiated the workflow
- ✅ Easy to filter agent commits (`git log --author="syn-app[bot]"`)

### Security Considerations

| Credential Type | Storage | Injection | Rotation |
|-----------------|---------|-----------|----------|
| **GitHub Token** | Vault/Secrets Manager | Environment variable | Manual/90 days |
| **GitHub App** | Vault (private key) | Generate on-demand | Automatic/1 hour |
| **SSH Key** | Vault | Base64 env var | Manual/365 days |

**Recommendations:**
1. **Local dev**: User's GitHub token (via `gh auth token`)
2. **CI/CD**: GitHub App with installation token
3. **Never**: Hardcode tokens in images or config files

### Implementation Checklist

- [ ] Add `GitConfig` to `IsolatedWorkspaceConfig`
- [ ] Inject git identity in `WorkspaceRouter.create()`
- [ ] Add credential injection (HTTPS token)
- [ ] Create GitHub App for production
- [ ] Add commit metadata template
- [ ] Document bot account setup
- [ ] Add integration tests for git operations
- [ ] Add credential rotation documentation

## Related ADRs

- **ADR-009**: Agentic Execution Architecture (original workspace design)
- **ADR-017**: Scalable Event Collection (multi-environment support)
- **ADR-004**: Environment Configuration (settings pattern)
- **ADR-022**: Secure Token Architecture (credential injection for workspaces)
- **ADR-023**: Workspace-First Execution Model (**enforcement of this architecture**)

## Hook Event Transport via stderr→stdout Merge (2026-02-18)

### Problem: `stderr=DEVNULL` Silently Discards Hook Events

The `agentic_isolation` docker provider's `stream()` method originally used:

```python
proc = await asyncio.create_subprocess_exec(
    *exec_cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.DEVNULL,  # ❌ Silently discards all hook output
)
```

The comment justifying `DEVNULL` was a misattributed concern about OS pipe buffer blocking
(unread `PIPE` fills up). The real effect was **silently discarding all Claude Code hook output**,
including git observability events emitted by `observe.py`.

### How Hook Events Flow

Claude Code hooks in the container run as subprocesses triggered by the CLI's hook system:

```
Container: claude code CLI
       │
       ├─► PreToolUse hook → observe.py
       │       │
       │       └─► detects git commit in Bash command
       │           emits JSON to stderr:
       │           {"event_type": "git_commit", "sha": "abc123", ...}
       │
       └─► stdout: normal agent output (JSONL)
```

Both channels flow through `docker exec`:

```
docker exec -i <container> python -u agent.py
              │
    ┌─────────┴──────────┐
    │                    │
  stdout              stderr
  (agent JSONL)   (hook JSONL + misc)
```

### Fix: Merge stderr into stdout

```python
proc = await asyncio.create_subprocess_exec(
    *exec_cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,  # ✅ Merge stderr so hook JSONL reaches engine
)
```

This is safe because `WorkflowExecutionEngine.parse_jsonl_line()` filters non-JSON lines
before attempting to parse them — any stderr noise (e.g., pip warnings, git status messages)
is silently ignored. Only valid JSON lines are processed.

### Complete Observability Pipeline (Containerized Agent)

```
Container                              Control Plane (Host)
─────────────────────────────────────  ──────────────────────────────────────
claude code CLI + observe.py hooks
       │
       ├─ agent JSONL  ─┐
       └─ hook JSONL   ─┤ (stderr merged → stdout via stderr=STDOUT)
                        │
              docker exec stream()
                        │
                        ▼
           WorkflowExecutionEngine
           .parse_jsonl_line()
                        │
                        ├─ tool events    → _record_observation("tool_*")
                        ├─ git events     → _record_observation("git_commit" etc.)
                        └─ other events   → filtered / ignored
                                 │
                                 ▼
                    agent_events (TimescaleDB)
                                 │
                                 ▼
                    SessionToolsProjection
                                 │
                                 ▼
                    Session timeline (dashboard)
```

### Rule

**Any workspace provider that streams agent output MUST merge stderr into stdout** (`stderr=STDOUT`
or equivalent). Do NOT use `stderr=DEVNULL` or `stderr=PIPE` (without reading it) in the
`stream()` method. Hook-based observability depends on this merge.

This applies to all current and future backends:
- Docker (`WorkspaceDockerProvider.stream()`)
- Local subprocess execution
- Any future Firecracker/VM stream adapters

---

## Implementation Notes (2025-12-15)

### Container Image

The `syn-workspace-claude` image is the reference implementation for Claude agents:

- **Location**: `docker/workspace/Dockerfile`
- **Build**: `just workspace-build`
- **Default**: Configured in `syn_shared.settings.workspace.docker_image`

Includes:
- `syn_agent_runner` package (runs inside container)
- `claude-agent-sdk` (agentic execution)
- `anthropic` SDK (API client)
- `gh` CLI (GitHub operations)
- `git` with credential helper for GitHub App token (see ADR-024)

### Contract Validation

`AgentContainerContract` validates container requirements before execution:

- **Location**: `packages/syn-adapters/src/syn_adapters/workspaces/contract.py`
- **Validates**: Required commands (`python`, `git`, `gh`) and modules (`syn_agent_runner`, `anthropic`, `claude_agent_sdk`)
- **Integration**: Called by `WorkspaceRouter.create()` after workspace setup
- **Fail-fast**: Raises `RuntimeError` with actionable fix instructions

### Compliance Tests

ADR compliance is verified by integration tests:

- **Location**: `packages/syn-adapters/tests/integration/test_adr_compliance.py`
- **Run**: `pytest tests/integration/test_adr_compliance.py -v`
- **Marker**: `@pytest.mark.integration`

## References

- [Firecracker Documentation](https://github.com/firecracker-microvm/firecracker)
- [gVisor Documentation](https://gvisor.dev/docs/)
- [Kata Containers](https://katacontainers.io/)
- [E2B Sandboxes](https://e2b.dev/docs)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Container Escape CVEs](https://sysdig.com/blog/container-escape-cve/)
