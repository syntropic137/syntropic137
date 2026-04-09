# ADR-023: Workspace-First Execution Model

**Status:** Accepted
**Date:** 2025-12-13
**Deciders:** @neural
**Tags:** execution, isolation, security, architecture, enforcement

## Context

The Syntropic137 has developed multiple architectural components that were designed independently and never fully integrated:

1. **ADR-009**: Agentic Execution Architecture - Defined `AgenticProtocol` and workspace concept
2. **ADR-014**: Workflow Execution Model - Separated templates from executions
3. **ADR-021**: Isolated Workspace Architecture - Defined isolation backends (Docker, Firecracker, gVisor)
4. **ADR-022**: Secure Token Architecture - Defined token vending and spend tracking

### The Problem

Despite having isolation infrastructure, the `WorkflowExecutionEngine` **bypasses all of it**:

```python
# Current (BROKEN) WorkflowExecutionEngine._execute_phase()
agent = self._agent_factory(phase.agent_config.provider)  # Direct agent call
response = await agent.complete(messages, config)          # No workspace!

# Events created but NEVER persisted:
_event = WorkflowExecutionStartedEvent(...)
# Note: In full implementation, wrap in EventEnvelope and publish
# await self._publisher.publish([EventEnvelope(event)])  ← COMMENTED OUT!
```

### Root Cause Analysis (5 Whys)

| Why | Finding |
|-----|---------|
| Why 1 | E2E test didn't use Docker containers |
| Why 2 | `WorkflowExecutionEngine` calls agents directly, bypassing `WorkspaceRouter` |
| Why 3 | Engine was designed for "completions" not "agentic execution in isolation" |
| Why 4 | No enforcement: `LocalWorkspace` works everywhere, `WorkspaceRouter` is optional |
| Why 5 | No **fail-fast** or **dependency inversion** design principles applied |

### Root Causes Identified

| ID | Root Cause | Security Impact |
|----|------------|-----------------|
| RC1 | Executor doesn't depend on `WorkspaceRouter` | Agents run on host with full access |
| RC2 | `LocalWorkspace` is public, usable anywhere | Bypasses isolation in production |
| RC3 | No environment-based enforcement | Silent fallback to unsafe mode |
| RC4 | Events created but not persisted | No audit trail for agent actions |
| RC5 | Agent runs on host, not in container | No security boundary |

## Decision

Adopt a **Workspace-First Execution Model** where:

1. **WorkspaceRouter is REQUIRED** - Engine cannot instantiate without it
2. **LocalWorkspace is TEST-ONLY** - Fails immediately in non-test environments
3. **Events are PERSISTED** - Via aggregate pattern, not logging
4. **Agents run INSIDE workspaces** - Never directly on host

### Core Principle: "No Workspace, No Execution"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       WorkflowExecutionEngine                                │
│                                                                              │
│  REQUIRED Dependencies (constructor validation fails without):               │
│  ├── workspace_router: WorkspaceRouter           ← No execution without     │
│  ├── execution_repository: ExecutionRepository   ← No events without        │
│  └── ...other repositories                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            WorkspaceRouter                                    │
│                                                                              │
│  Environment-Based Selection:                                                 │
│  ├── TEST        → InMemoryWorkspace (fast, no Docker)                       │
│  ├── DEVELOPMENT → DockerHardened or gVisor                                  │
│  └── PRODUCTION  → Firecracker or Cloud (E2B)                                │
│                                                                              │
│  FAIL-FAST Rules:                                                            │
│  ├── Non-TEST + LocalWorkspace requested → RuntimeError                      │
│  ├── PRODUCTION + no backend available   → RuntimeError                      │
│  └── DEVELOPMENT + no backend            → RuntimeError with guidance        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Enforcement Mechanisms

#### 1. LocalWorkspace Fails in Non-Test

```python
class LocalWorkspace(WorkspaceProtocol):
    """Workspace using local filesystem - TEST ENVIRONMENT ONLY."""

    def __init__(self, path: Path) -> None:
        settings = get_settings()
        if not settings.is_test:
            raise RuntimeError(
                f"LocalWorkspace cannot be used in '{settings.app_environment}' environment. "
                "Use WorkspaceRouter.get_workspace() for isolated execution. "
                "See ADR-023: Workspace-First Execution Model."
            )
        self._path = path
```

#### 2. WorkspaceRouter is Required Dependency

```python
class WorkflowExecutionEngine:
    def __init__(
        self,
        workspace_router: WorkspaceRouter,              # REQUIRED
        execution_repository: ExecutionRepository,      # REQUIRED
        workflow_repository: WorkflowRepository,
        artifact_repository: ArtifactRepository,
    ) -> None:
        if workspace_router is None:
            raise TypeError(
                "workspace_router is required - agents MUST run in isolated workspaces. "
                "See ADR-023: Workspace-First Execution Model."
            )
        if execution_repository is None:
            raise TypeError(
                "execution_repository is required - events MUST be persisted. "
                "See ADR-023: Workspace-First Execution Model."
            )

        self._workspace_router = workspace_router
        self._executions = execution_repository
```

#### 3. Events Persisted via Aggregate Pattern

```python
async def execute(self, workflow_id: str, inputs: dict) -> ExecutionResult:
    # Create aggregate
    execution = WorkflowExecutionAggregate()

    # Start execution (emits WorkflowExecutionStarted)
    execution._handle_command(StartExecutionCommand(
        execution_id=execution_id,
        workflow_id=workflow_id,
        ...
    ))

    # PERSIST immediately - no silent drops
    await self._executions.save(execution)

    for phase in workflow.phases:
        await self._execute_phase(execution, phase, ctx)
        # PERSIST after each phase
        await self._executions.save(execution)

    # Complete execution (emits WorkflowCompleted)
    execution._handle_command(CompleteExecutionCommand(...))
    await self._executions.save(execution)
```

#### 4. Agent Runs Inside Workspace

```python
async def _execute_phase(self, execution, phase, ctx):
    config = WorkspaceConfig(
        execution_id=execution.id,
        phase_id=phase.phase_id,
    )

    # Get isolated workspace
    async with self._workspace_router.get_workspace(config) as workspace:
        # Inject credentials (from ADR-022)
        await self._inject_credentials(workspace)

        # Run agent INSIDE workspace
        result = await workspace.execute([
            "python", "-m", "claude_agent",
            "--task", phase.prompt,
            "--workspace", "/workspace",
        ])

        # Collect artifacts
        artifacts = await workspace.collect_artifacts("/workspace/output")
```

### Execution Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Syn137 Control Plane                                 │
│                                                                              │
│  ┌─────────────────┐   ┌────────────────────────┐   ┌───────────────────┐   │
│  │ WorkflowEngine  │──▶│ WorkflowExecution      │──▶│ Event Store       │   │
│  │ (orchestrates)  │   │ Aggregate (events)     │   │ (PostgreSQL)      │   │
│  └────────┬────────┘   └────────────────────────┘   └───────────────────┘   │
│           │                                                                  │
│           │  1. Get isolated workspace                                       │
│           ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         WorkspaceRouter                                  │ │
│  │  TEST → InMemory | DEV → Docker | PROD → Firecracker/E2B               │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│           │                                                                  │
└───────────┼──────────────────────────────────────────────────────────────────┘
            │  2. docker run / firecracker / API call
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Isolated Workspace (Container/VM)                        │
│                                                                              │
│  3. Credentials injected via sidecar (ADR-022):                             │
│     - GitHub App token (x-access-token)                                      │
│     - Claude API key (via TokenVendingService)                               │
│                                                                              │
│  4. Agent executes:                                                          │
│     ┌───────────────────────────────────────────────────────────────────┐   │
│     │  claude-agent-sdk / Claude CLI                                     │   │
│     │  - Reads/writes files in /workspace                               │   │
│     │  - Makes API calls through egress proxy                            │   │
│     │  - Hooks fire and log to .agentic/analytics/                       │   │
│     └───────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  5. Artifacts collected from /workspace/output                               │
│                                                                              │
│  Network: Egress proxy → allowlist only (api.anthropic.com, github.com)     │
│  Resources: --memory=512m --cpus=0.5 --pids-limit=100                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Alternatives Considered

### Alternative 1: Optional Workspace (Status Quo)

Keep workspace optional, add warnings when not used.

**Why Rejected:**
- Warnings are ignored
- Security is opt-in, not enforced
- "Just for local dev" becomes production habit

### Alternative 2: Feature Flag for Isolation

Use `SYN_ENABLE_ISOLATION=true` to enable workspace requirement.

**Why Rejected:**
- Creates two code paths to maintain
- Flag will be `false` in local dev, hiding issues
- Security should be default, not configured

### Alternative 3: Soft Enforcement (Deprecation)

Log warnings for 3 months, then enforce.

**Why Rejected:**
- Delays security improvements
- Creates technical debt
- Current state is fundamentally broken (events not persisted)

## Consequences

### Positive

✅ **Security by Default**: All agents isolated from host and each other

✅ **Audit Trail**: All events persisted to event store

✅ **Consistent Architecture**: ADRs now align with implementation

✅ **Fail-Fast**: Issues caught immediately, not in production

✅ **Credential Safety**: Tokens never touch agent code directly (ADR-022)

### Negative

⚠️ **Breaking Change**: Code using `LocalWorkspace` outside tests will fail

⚠️ **Docker Required**: Development requires Docker (or gVisor/E2B)

⚠️ **Startup Overhead**: ~125ms-2s per workspace (mitigated by pre-warming)

⚠️ **Test Changes**: Some tests may need adjustment

### Mitigations

1. **Breaking Change**: Clear error message with migration guidance
2. **Docker Required**: Multiple backend options, clear setup docs
3. **Startup Overhead**: Pre-warmed container pool, InMemoryWorkspace for tests
4. **Test Changes**: Maintain `is_test` environment for fast tests

## Implementation

See: `PROJECT-PLAN_20251213_WORKSPACE-FIRST-EXECUTION.md`

### Milestone Summary

1. **ADR-023** (this document) - Define architecture
2. **LocalWorkspace Fail-Fast** - Environment enforcement
3. **Engine Refactor** - Required DI, aggregate pattern
4. **Agent in Workspace** - Execution model
5. **E2E Test** - Validation
6. **Documentation** - Cleanup and handoff

## Related ADRs

| ADR | Relationship |
|-----|--------------|
| ADR-009 | Original agentic execution - **superseded for execution model** |
| ADR-014 | Workflow execution model - **implementation details here** |
| ADR-021 | Isolated workspace architecture - **enforcement specified here** |
| ADR-022 | Secure token architecture - **credential injection integrated** |

## Implementation Notes (2025-12-15)

### Default Configuration

```python
# packages/syn-shared/src/syn_shared/settings/workspace.py
docker_image = "syn-workspace-claude:latest"
```

### Automated Build

The `just dev-force` command automatically builds the workspace image if missing:

```bash
just dev-force  # Checks for image, builds if needed, starts stack
just workspace-build  # Build image manually
```

### Contract Enforcement

`AgentContainerContract` ensures containers meet requirements before agent execution:

```python
# Called automatically by WorkspaceRouter.create()
result = await AgentContainerContract.validate(workspace, executor)
if not result.passed:
    raise RuntimeError(result.error_message)
```

### Compliance Tests

ADR compliance is verified by integration tests:

- **Location**: `packages/syn-adapters/tests/integration/test_adr_compliance.py`
- **Run**: `pytest tests/integration/test_adr_compliance.py -v`

### Key Files

| Component | Location |
|-----------|----------|
| Workspace Image | `docker/workspace/Dockerfile` |
| Contract Validation | `syn_adapters.workspaces.contract` |
| Workspace Router | `syn_adapters.workspaces.router` |
| Settings | `syn_shared.settings.workspace` |
| Compliance Tests | `tests/integration/test_adr_compliance.py` |

## References

- [5 Whys Root Cause Analysis](https://en.wikipedia.org/wiki/Five_whys)
- [Dependency Inversion Principle](https://en.wikipedia.org/wiki/Dependency_inversion_principle)
- [Fail-Fast Design](https://en.wikipedia.org/wiki/Fail-fast)
- [ADR-021: Isolated Workspace Architecture](./ADR-021-isolated-workspace-architecture.md)
- [ADR-022: Secure Token Architecture](./ADR-022-secure-token-architecture.md)

---

## 2026-04-09 Update: Setup Phase Now Pre-Clones Repositories (ADR-058)

[ADR-058: Workspace Hydration](ADR-058-workspace-hydration.md) extends the setup phase (introduced in ADR-024) to pre-clone all declared repositories before the agent process starts.

### Setup Phase as Infrastructure Work

This change is a direct application of the principle established in this ADR: **infrastructure work belongs in the setup phase, not in agent execution.**

Before this update, the first tool call for every workflow execution was a `Bash: git clone ...` event. Cloning a repository is not a task decision — it is infrastructure provisioning. It has the same character as configuring git credentials or writing `~/.git-credentials`: mechanical, predictable, and safely handled without agent reasoning.

Moving git clone into the setup phase completes the boundary between infrastructure setup (pre-agent) and task execution (agent):

```
SETUP PHASE (infrastructure)           AGENT PHASE (task work)
──────────────────────────────         ────────────────────────────
Configure git credentials              Turn 1: actual task action
Clone declared repositories            Turn 2: code change / PR
Inject /workspace/CLAUDE.md            Turn 3: ...
Clear secrets
```

### Observability Impact

The Syntropic137 dashboard timeline now shows the agent's first tool call as the first unit of meaningful task work. Git clone events no longer appear in agent session tool traces — they happen in the setup phase before the session begins.

This makes cost attribution cleaner: setup-phase time is infrastructure overhead; agent-session time is where task value is created.

### CLAUDE.md Context Loading

As a consequence of pre-cloning, a synthetic `/workspace/CLAUDE.md` can be injected after repos are cloned and before the agent starts (see ADR-058, ADR-036 update). This means Claude Code's at-launch CLAUDE.md discovery loads full project context from turn 1 — a capability that was impossible when repos didn't exist at launch time.

### Idempotency Requirement Reinforced

The setup-phase clone commands use idempotency guards (`[ -d "..." ] || git clone ...`). This is consistent with the Processor To-Do List crash-recovery guarantee described in the main architecture documentation: setup phase handlers must be safe to re-run after a crash. Pre-cloning with an idempotency guard satisfies this requirement.
