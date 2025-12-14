# Isolated Workspace Architecture

This module provides **isolation-first** workspace management for agent execution.
All agents run in isolated environments by default, protecting against compromised
or malicious code execution.

See [ADR-021: Isolated Workspace Architecture](../../../../../docs/adrs/ADR-021-isolated-workspace-architecture.md)
See [ADR-023: Workspace-First Execution Model](../../../../../docs/adrs/ADR-023-workspace-first-execution-model.md)

## ⚠️ Important: Test-Only Workspaces (ADR-023)

`LocalWorkspace` and `InMemoryWorkspace` provide **NO ISOLATION** and are
**TEST ONLY**. They will raise errors in development, staging, or production:

```python
# ❌ FAILS in dev/prod - LocalWorkspace is TEST ONLY
from aef_adapters.workspaces import LocalWorkspace
workspace = await LocalWorkspace.create(config)  # NonIsolatedWorkspaceError!

# ✅ WORKS everywhere - WorkspaceRouter selects isolated backend
from aef_adapters.workspaces import get_workspace_router
router = get_workspace_router()
async with router.create(config) as workspace:
    # Uses Docker, gVisor, Firecracker, or E2B
    ...
```

**Always use `WorkspaceRouter` for development and production.**

## Quick Start

```python
from aef_adapters.workspaces import WorkspaceRouter, IsolatedWorkspaceConfig
from aef_adapters.agents.agentic_types import WorkspaceConfig

# Create router (automatically selects best backend)
router = WorkspaceRouter()

# Create workspace config
base_config = WorkspaceConfig(session_id="my-session")
config = IsolatedWorkspaceConfig(base_config=base_config)

# Create isolated workspace
async with router.create(config) as workspace:
    # Execute commands safely inside isolation
    exit_code, stdout, stderr = await router.execute_command(
        workspace, ["python", "-c", "print('Hello from isolation!')"]
    )
    print(stdout)  # Hello from isolation!
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      WorkspaceRouter                             │
│  - Automatic backend selection                                   │
│  - Fallback to alternatives                                      │
│  - Overflow to cloud                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Firecracker  │    │    gVisor     │    │     E2B       │
│   (MicroVM)   │    │   (Docker)    │    │   (Cloud)     │
│               │    │               │    │               │
│ ✓ Separate    │    │ ✓ Syscall     │    │ ✓ Managed     │
│   kernel      │    │   intercept   │    │   isolation   │
│ ✓ KVM-based   │    │ ✓ User-space  │    │ ✓ Any platform│
│ ✓ ~125ms boot │    │   kernel      │    │ ✓ Overflow    │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │
        │            ┌────────┴────────┐
        │            │                 │
        ▼            ▼                 ▼
   Linux + KVM   ┌─────────┐    ┌─────────────┐
                 │ runsc   │    │ Hardened    │
                 │ runtime │    │ Docker      │
                 └─────────┘    └─────────────┘
```

## Isolation Backends

### Priority Order (Strongest to Weakest)

| Priority | Backend | Isolation Level | Platform | Use Case |
|----------|---------|-----------------|----------|----------|
| 1 | **Firecracker** | Kernel-level | Linux + KVM | Production (recommended) |
| 2 | **Kata** | Kernel-level | Kubernetes | K8s environments |
| 3 | **gVisor** | Syscall-level | Docker + runsc | macOS, strong isolation |
| 4 | **Docker Hardened** | Container-level | Docker | Fallback when no runsc |
| 5 | **Cloud (E2B)** | Managed | Any | Overflow capacity |

### Firecracker (Recommended for Production)

```python
from aef_adapters.workspaces import FirecrackerWorkspace

# Check availability
if FirecrackerWorkspace.is_available():
    async with FirecrackerWorkspace.create(config) as workspace:
        # Running in a separate kernel
        await FirecrackerWorkspace.execute_command(
            workspace, ["python", "untrusted_script.py"]
        )
```

**Requirements:**
- Linux with KVM (`/dev/kvm`)
- Firecracker binary installed
- Pre-built kernel and rootfs images

**Advantages:**
- Strongest isolation (separate kernel per workspace)
- Fast boot (~125ms)
- Low overhead (~5MB per VM)
- Battle-tested (AWS Lambda, Fly.io)

### gVisor (macOS Compatible)

```python
from aef_adapters.workspaces import GVisorWorkspace

if GVisorWorkspace.is_available():
    async with GVisorWorkspace.create(config) as workspace:
        # Running with syscall interception
        await GVisorWorkspace.execute_command(
            workspace, ["python", "script.py"]
        )
```

**Requirements:**
- Docker with gVisor runtime (runsc)
- Docker Desktop on macOS includes runsc

**Advantages:**
- No direct kernel access (syscalls intercepted)
- Works on macOS via Docker Desktop
- Compatible with existing Docker images

### Hardened Docker (Fallback)

```python
from aef_adapters.workspaces import HardenedDockerWorkspace

if HardenedDockerWorkspace.is_available():
    async with HardenedDockerWorkspace.create(config) as workspace:
        await HardenedDockerWorkspace.execute_command(
            workspace, ["python", "script.py"]
        )
```

**Security Hardening Applied:**
- `--cap-drop=ALL` (drop all capabilities)
- `--security-opt=no-new-privileges:true`
- `--read-only` (read-only root filesystem)
- `--network=none` (network isolation)
- Resource limits (memory, CPU, PIDs)
- AppArmor/seccomp profiles

### E2B Cloud (Overflow)

```python
from aef_adapters.workspaces import E2BWorkspace

if E2BWorkspace.is_available():
    async with E2BWorkspace.create(config) as workspace:
        await E2BWorkspace.execute_command(
            workspace, ["python", "script.py"]
        )
```

**Requirements:**
- E2B API key (`AEF_WORKSPACE_CLOUD_API_KEY`)
- Network access to api.e2b.dev
- `aiohttp` package installed

**Advantages:**
- Works on any platform
- No local infrastructure needed
- Automatic scaling

## Configuration

### Environment Variables

```bash
# Backend selection (auto-detected if not set)
AEF_WORKSPACE_ISOLATION_BACKEND=gvisor  # firecracker|kata|gvisor|docker_hardened|cloud

# Capacity
AEF_WORKSPACE_POOL_SIZE=100           # Pre-warmed instances
AEF_WORKSPACE_MAX_CONCURRENT=1000     # Hard limit

# Cloud overflow
AEF_WORKSPACE_ENABLE_CLOUD_OVERFLOW=true
AEF_WORKSPACE_CLOUD_PROVIDER=e2b      # e2b|modal
AEF_WORKSPACE_CLOUD_API_KEY=...       # API key for cloud provider

# Docker settings
AEF_WORKSPACE_DOCKER_IMAGE=aef-workspace:latest
AEF_WORKSPACE_DOCKER_RUNTIME=runsc    # runsc|runc
AEF_WORKSPACE_DOCKER_NETWORK=none     # none|bridge

# Security policies
AEF_SECURITY_ALLOW_NETWORK=false      # Network access
AEF_SECURITY_ALLOWED_HOSTS=           # Allowlist (comma-separated)
AEF_SECURITY_READ_ONLY_ROOT=true      # Read-only root filesystem
AEF_SECURITY_MAX_WORKSPACE_SIZE=1Gi   # Workspace tmpfs size
AEF_SECURITY_MAX_MEMORY=512Mi         # Memory limit per workspace
AEF_SECURITY_MAX_CPU=0.5              # CPU limit (cores)
AEF_SECURITY_MAX_PIDS=100             # Process limit
AEF_SECURITY_MAX_EXECUTION_TIME=3600  # Hard timeout (seconds)
```

### Programmatic Configuration

```python
from aef_shared.settings import (
    WorkspaceSettings,
    WorkspaceSecuritySettings,
    IsolationBackend,
)

# Custom security settings
security = WorkspaceSecuritySettings(
    allow_network=True,
    allowed_hosts="pypi.org,api.github.com",
    max_memory="1Gi",
    max_cpu=2.0,
)

# Create config with custom security
config = IsolatedWorkspaceConfig(
    base_config=base_config,
    security=security,
    isolation_backend=IsolationBackend.GVISOR,
)
```

## Security Model

### Threat Model

All coding agents are assumed potentially compromised. Isolation protects against:

1. **Sandbox Escape** - Agent attempts to access host system
2. **Resource Exhaustion** - Fork bombs, memory exhaustion
3. **Network Attacks** - Exfiltration, lateral movement
4. **Privilege Escalation** - Kernel exploits

### Defense in Depth

```
┌─────────────────────────────────────────┐
│           Agent Code                     │
├─────────────────────────────────────────┤
│  Resource Limits (CPU, Memory, PIDs)     │
├─────────────────────────────────────────┤
│  Capability Dropping (CAP_DROP=ALL)      │
├─────────────────────────────────────────┤
│  Seccomp/AppArmor Profiles               │
├─────────────────────────────────────────┤
│  Network Isolation (--network=none)      │
├─────────────────────────────────────────┤
│  Read-Only Root Filesystem               │
├─────────────────────────────────────────┤
│  Kernel Isolation (Firecracker/gVisor)   │
├─────────────────────────────────────────┤
│           Host System                    │
└─────────────────────────────────────────┘
```

## API Reference

### WorkspaceRouter

```python
class WorkspaceRouter:
    def get_available_backends(self) -> list[IsolationBackend]:
        """Get list of available backends on this platform."""

    def get_best_backend(self) -> IsolationBackend:
        """Get the best available backend (highest priority)."""

    async def create(
        self,
        config: IsolatedWorkspaceConfig,
        *,
        backend: IsolationBackend | None = None,
        allow_overflow: bool = True,
    ) -> AsyncContextManager[IsolatedWorkspace]:
        """Create an isolated workspace."""

    async def execute_command(
        self,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute command in workspace, returns (exit_code, stdout, stderr)."""

    async def health_check(self, workspace: IsolatedWorkspace) -> bool:
        """Check if workspace is healthy."""

    async def inject_context(
        self,
        workspace: IsolatedWorkspace,
        files: list[tuple[str, bytes]],
        metadata: dict | None = None,
    ) -> None:
        """Inject files into workspace."""

    async def collect_artifacts(
        self,
        workspace: IsolatedWorkspace,
        patterns: list[str] | None = None,
    ) -> list[tuple[str, bytes]]:
        """Collect output artifacts from workspace."""
```

### IsolatedWorkspace

```python
@dataclass
class IsolatedWorkspace:
    path: Path                          # Local workspace path
    config: WorkspaceConfig             # Original config
    isolation_backend: IsolationBackend # Which backend is used
    container_id: str | None            # Docker container ID
    vm_id: str | None                   # Firecracker VM ID
    sandbox_id: str | None              # Cloud sandbox ID
    security: WorkspaceSecuritySettings # Applied security

    # Lifecycle
    created_at: datetime
    started_at: datetime | None
    terminated_at: datetime | None

    # Resource tracking
    memory_used_bytes: int
    cpu_time_seconds: float
    network_bytes_in: int
    network_bytes_out: int

    @property
    def is_running(self) -> bool: ...
    @property
    def duration_seconds(self) -> float | None: ...
    @property
    def isolation_id(self) -> str | None: ...
```

## Performance Benchmarks

Run benchmarks to measure workspace performance on your system:

```bash
# Quick benchmark
just perf-check

# Full benchmark suite
just perf-all
```

### Benchmark Results (macOS, docker_hardened)

```
╭─────────────────────────────────╮
│ Workspace Performance Benchmark │
╰─────────────────────────────────╯

Backend: docker_hardened
Iterations: 5
Success Rate: 100.0%

                   Timing Statistics
┏━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Metric       ┃   Min ┃   Max ┃  Mean ┃   P95 ┃   P99 ┃
┡━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ Create Time  │ 133ms │ 217ms │ 179ms │ 215ms │ 216ms │
│ Destroy Time │ 5.36s │ 5.87s │ 5.53s │ 5.80s │ 5.85s │
│ Total Cycle  │ 5.53s │ 6.09s │ 5.72s │ 6.02s │ 6.08s │
└──────────────┴───────┴───────┴───────┴───────┴───────┘
```

### Parallel Scaling

```
╭────────────────────────────╮
│ Parallel Scaling Benchmark │
╰────────────────────────────╯

Backend: docker_hardened
Concurrent Workspaces: 10
Success Rate: 100.0%

Results:
  Total Time:        7.91s
  Avg per Workspace: 791ms
  Sequential Est.:   75.52s
  Speedup:           9.54x  ⬅️ Near-linear scaling!
```

### Key Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| **Container Create** | ~170ms | Docker container startup |
| **Container Destroy** | ~5.5s | Docker stop timeout (configurable) |
| **Parallel Speedup (10x)** | **9.54x** | Near-linear scaling |
| **Throughput** | ~5 workspaces/min | With default settings |

### Running Custom Benchmarks

```bash
# Single workspace timing
uv run python -m aef_perf single --iterations 10

# Parallel scaling test
uv run python -m aef_perf parallel --count 10

# Throughput test
uv run python -m aef_perf throughput --duration 30

# Compare all backends
uv run python -m aef_perf compare

# Export to JSON for CI
uv run python -m aef_perf single --output results.json
```

## Git Identity Injection

Workspaces automatically configure Git identity for commits:

```bash
# Environment variables (set these for commit author)
export AEF_GIT_USER_NAME="AEF Bot"
export AEF_GIT_USER_EMAIL="aef-bot@example.com"
export AEF_GIT_TOKEN=ghp_xxx  # GitHub PAT for HTTPS auth
```

**Precedence Order:**
1. Workflow override (per-workflow config)
2. Environment variables (`AEF_GIT_*`)
3. Local git config (dev/test only)

```python
from aef_shared.settings.workspace import GitIdentitySettings

# Override for specific workflow
git_override = GitIdentitySettings(
    user_name="Workflow Bot",
    user_email="workflow@example.com",
)

config = IsolatedWorkspaceConfig(
    base_config=base_config,
    git_identity_override=git_override,
)
```

## API Key Injection

LLM API keys are automatically injected into containers:

```bash
# Set API keys
export ANTHROPIC_API_KEY=sk-ant-xxx
export OPENAI_API_KEY=sk-xxx

# POC test
just poc-claude-api
```

Keys are written to `~/.bashrc` and `~/.profile` inside the container.

## Container Logging

Structured JSON logging inside containers with secret redaction:

```bash
# Configuration
export AEF_LOGGING_LEVEL=INFO
export AEF_LOGGING_FORMAT=json
export AEF_LOGGING_REDACT_SECRETS=true
export AEF_LOGGING_LOG_FILE_PATH=/workspace/.logs/agent.jsonl
```

### Reading Logs (Orchestrator)

```python
from aef_adapters.workspaces.logging import ContainerLogStreamer

streamer = ContainerLogStreamer(container_id="abc123")
logs = await streamer.get_recent_logs(lines=100)

# Stream logs (like tail -f)
async for log_entry in streamer.stream_logs():
    print(f"[{log_entry.level}] {log_entry.message}")
```

### Reading Logs (Inner Agent)

```python
from aef_adapters.workspaces.logging import ViewContainerLogsTool

tool = ViewContainerLogsTool()
output = await tool.execute(lines=50, level="ERROR")
```

## Network Allowlist (Egress Proxy)

Control outbound network access via mitmproxy:

```bash
# Build and start egress proxy
just proxy-build
just proxy-start

# Test allowlist enforcement
just poc-allowlist
```

### Default Allowed Hosts

| Host | Purpose |
|------|---------|
| api.anthropic.com | Claude API |
| api.openai.com | OpenAI API |
| github.com | Git operations |
| api.github.com | GitHub API |
| pypi.org | Python packages |
| files.pythonhosted.org | Package files |
| registry.npmjs.org | npm packages |

### Custom Allowlist

```bash
# Set custom allowlist
export ALLOWED_HOSTS="api.anthropic.com,github.com,custom.api.com"

# Wildcard subdomains
export ALLOWED_HOSTS="*.github.com,*.anthropic.com"
```

## Testing

```bash
# Run all workspace tests
uv run pytest packages/aef-adapters/tests/workspaces/ -v

# Run orchestration factory tests
uv run pytest packages/aef-adapters/tests/test_orchestration_factory.py -v

# Run with Docker integration (requires Docker)
AEF_RUN_DOCKER_TESTS=1 uv run pytest packages/aef-adapters/tests/ -v -m docker

# POC validation commands
just poc-git-identity  # Test git identity injection
just poc-claude-api    # Test API key injection
just poc-logging       # Test container logging
just poc-allowlist     # Test network allowlist
```

## Troubleshooting

### "No isolation backend available"

1. **Install Docker**: Required for gVisor and Hardened Docker backends
2. **Configure E2B**: Set `AEF_WORKSPACE_CLOUD_API_KEY` for cloud fallback
3. **Check KVM**: For Firecracker, ensure `/dev/kvm` exists

### gVisor not working

```bash
# Check if runsc is available
docker info --format '{{json .Runtimes}}' | grep runsc

# Install gVisor on Linux
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt update && sudo apt install runsc
```

### Firecracker not working

```bash
# Check KVM access
ls -la /dev/kvm

# Install Firecracker
curl -L https://github.com/firecracker-microvm/firecracker/releases/download/v1.5.0/firecracker-v1.5.0-x86_64.tgz | tar xz
sudo mv release-v1.5.0-x86_64/firecracker-v1.5.0-x86_64 /usr/local/bin/firecracker
```

## Related Documentation

- [ADR-021: Isolated Workspace Architecture](../../../../../docs/adrs/ADR-021-isolated-workspace-architecture.md)
- [ADR-023: Workspace-First Execution Model](../../../../../docs/adrs/ADR-023-workspace-first-execution-model.md)
- [ADR-009: Agentic Execution Architecture](../../../../../docs/adrs/ADR-009-agentic-execution-architecture.md)
- [Settings Configuration](../../shared/settings/README.md)
