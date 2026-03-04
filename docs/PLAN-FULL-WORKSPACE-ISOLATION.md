# Plan: Full Workspace Isolation for Agent Execution

**Status**: Planning
**Created**: 2024-12-11
**Related**: ADR-023, ADR-021
**Priority**: High

## Problem Statement

Currently, the `WorkflowExecutionEngine` has `WorkspaceRouter` as a required dependency (per ADR-023), but agent execution still happens in the **host process** with only `cwd` pointing to the workspace path:

```python
# Current (partial isolation)
# TODO: Create isolated workspace via self._router.create() and
# execute all phases inside it. For now, we use the router for DI
# enforcement but agent execution happens in host process.
```

This means:
1. ✅ **DI is enforced** - Router is required, LocalWorkspace fails outside tests
2. ❌ **Execution is NOT isolated** - Agent runs in orchestrator process
3. ❌ **Secrets exposed** - API keys in orchestrator memory
4. ❌ **No resource limits** - Agent can consume unlimited resources

## Goal

Execute agents **inside** isolated workspace containers, with **one workspace per phase** (stateless agents).

### Key Principle: Stateless Phases

Each phase is independent:
- Gets a **fresh workspace** (no shared state)
- Receives **artifacts as input** (from previous phases)
- Produces **artifacts as output** (for next phases)
- Workspace is **destroyed** after phase completes

### Artifact Types

Artifacts stored in the artifact DB can be:

| Type | Description | Example |
|------|-------------|---------|
| **Content** | Actual file content | `code`, `markdown`, `json` |
| **GitHub Commit** | Reference to commit SHA | `github_commit` → `abc123` |
| **GitHub PR** | Reference to pull request | `github_pr` → `#42` |
| **GitHub File** | File at specific commit | `github_file` → `src/main.py@abc123` |
| **URL** | External resource link | `url` → `https://docs.example.com` |

This allows agents to pass context like "I created PR #42" to the next phase without
duplicating all the code - just the reference for additional context.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Orchestrator (Host)                              │
│                                                                          │
│   Phase 1                    Phase 2                    Phase 3          │
│   ┌──────────────────┐      ┌──────────────────┐      ┌──────────────┐  │
│   │ Workspace A      │      │ Workspace B      │      │ Workspace C  │  │
│   │ ┌──────────────┐ │      │ ┌──────────────┐ │      │ ┌──────────┐ │  │
│   │ │ Agent        │ │      │ │ Agent        │ │      │ │ Agent    │ │  │
│   │ │ (Research)   │ │─────▶│ │ (Implement)  │ │─────▶│ │ (Review) │ │  │
│   │ └──────────────┘ │      │ └──────────────┘ │      │ └──────────┘ │  │
│   │                  │      │                  │      │              │  │
│   │ Artifacts OUT ───┼──────┼▶ Artifacts IN   │      │              │  │
│   └──────────────────┘      │ Artifacts OUT ──┼──────┼▶ Artifacts   │  │
│         ↓ destroy           └──────────────────┘      └──────────────┘  │
│                                   ↓ destroy                ↓ destroy    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Per-Phase Flow

```
1. Create isolated workspace (Docker/gVisor/Firecracker)
2. Inject artifacts from previous phases
3. Inject credentials (GitHub token, API keys)
4. Execute agent inside workspace
5. Stream events to aggregate
6. Collect output artifacts
7. Destroy workspace
8. Next phase...
```

## Proposed Solution

### Option A: Subprocess Execution (Recommended)

Run a Python subprocess inside the workspace that executes the agent:

```python
async def _execute_phase_isolated(
    self,
    phase: WorkflowPhase,
    ctx: ExecutionContext,
    aggregate: WorkflowExecutionAggregate,
) -> PhaseResult:
    # 1. Create isolated workspace
    config = IsolatedWorkspaceConfig(...)
    async with self._router.create(config) as workspace:
        # 2. Inject task context (files, credentials)
        await workspace.inject_context(
            files=[("task.json", task_json_bytes)],
            metadata={"phase": phase.name},
        )

        # 3. Execute agent subprocess INSIDE workspace
        exit_code, stdout, stderr = await workspace.execute_command([
            "python", "-m", "syn_agent_runner",
            "--task-file", "/workspace/task.json",
            "--output-dir", "/workspace/output",
        ])

        # 4. Stream events from agent (via file or socket)
        async for event in self._stream_agent_events(workspace):
            yield event

        # 5. Collect artifacts
        artifacts = await workspace.collect_artifacts(["output/*"])

        return PhaseResult(success=exit_code == 0, artifacts=artifacts)
```

**Pros**:
- Clear isolation boundary
- Works with any container runtime
- Agent process has its own memory space
- Easy to resource-limit

**Cons**:
- Need to package `syn_agent_runner` in workspace image
- Event streaming requires IPC (files, sockets, or stdout)
- Adds startup latency (~200ms)

### Option B: SDK in Container Mode

Configure `claude-agent-sdk` to run in "container mode" where it connects back to the orchestrator:

```python
# Agent in container connects to orchestrator via gRPC/WebSocket
async def execute_in_container():
    async with workspace.execute_interactive() as session:
        session.write_stdin(task_prompt)
        async for line in session.read_stdout():
            yield parse_event(line)
```

**Pros**:
- Real-time streaming
- SDK handles complexity

**Cons**:
- Requires SDK support (not yet available)
- More complex networking

### Option C: Event-Driven Execution

Agent writes events to a file, orchestrator watches and collects:

```python
# Agent writes to /workspace/.events/
{"type": "tool_use", "tool": "Write", "path": "hello.py"}
{"type": "progress", "turn": 1, "tokens": 150}
{"type": "completed", "result": "Created hello.py"}

# Orchestrator polls or uses inotify
async for event_file in watch_events(workspace):
    event = parse_event(await workspace.read_file(event_file))
    yield event
```

**Pros**:
- Simple, works everywhere
- No network needed

**Cons**:
- Polling latency
- File cleanup needed

## Recommended Implementation: Option A

### Phase 1: Agent Runner Package

Create `packages/syn-agent-runner/` - a minimal package that:
1. Reads task from JSON file
2. Executes via `claude-agent-sdk`
3. Writes events to stdout (JSONL)
4. Writes artifacts to output dir

```python
# syn_agent_runner/__main__.py
import json
import sys
from pathlib import Path

def main():
    task_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    task = json.loads(task_file.read_text())

    # Execute with claude-agent-sdk
    for event in execute_task(task):
        # Write event as JSONL to stdout
        print(json.dumps(event.to_dict()), flush=True)

    # Artifacts are already in output_dir
```

### Phase 2: Workspace Image

Update `docker/workspace/Dockerfile`:

```dockerfile
FROM python:3.12-slim

# Install agent runner
RUN pip install syn-agent-runner

# Entry point
ENTRYPOINT ["python", "-m", "syn_agent_runner"]
```

### Phase 3: Engine Integration

Update `WorkflowExecutionEngine._execute_phase` to create **one workspace per phase**:

```python
async def _execute_phase(
    self,
    workflow: Workflow,
    phase: WorkflowPhase,
    ctx: ExecutionContext,
    aggregate: WorkflowExecutionAggregate,
) -> None:
    """Execute a single phase in its own isolated workspace.

    Each phase is stateless:
    - Fresh workspace created
    - Previous artifacts injected as input
    - Agent executes
    - Output artifacts collected
    - Workspace destroyed
    """
    # 1. Create workspace config for THIS phase
    config = IsolatedWorkspaceConfig(
        base_config=WorkspaceConfig(
            session_id=f"{ctx.execution_id}-{phase.phase_id}",
            phase_id=phase.phase_id,
        ),
        security=self._get_security_settings(phase),
    )

    # 2. Create isolated workspace (destroyed on exit)
    async with self._router.create(config) as workspace:
        # 3. Inject artifacts from PREVIOUS phases
        previous_artifacts = self._get_previous_phase_artifacts(ctx, phase)
        await workspace.inject_context(
            files=previous_artifacts,
            metadata={"phase": phase.name, "inputs": ctx.inputs},
        )

        # 4. Prepare task with phase prompt
        task_data = self._prepare_task(phase, ctx)
        await workspace.write_file(
            "task.json",
            json.dumps(task_data).encode(),
        )

        # 5. Execute agent INSIDE workspace
        process = await workspace.execute_streaming([
            "python", "-m", "syn_agent_runner",
            "--task", "/workspace/task.json",
            "--output", "/workspace/output",
        ])

        # 6. Stream events from stdout (JSONL)
        async for line in process.stdout:
            event = json.loads(line)
            self._handle_agent_event(event, aggregate)

        # 7. Wait for completion
        exit_code = await process.wait()

        # 8. Collect OUTPUT artifacts for next phases
        artifacts = await workspace.collect_artifacts(
            patterns=["output/**/*"],
        )
        ctx.phase_artifacts[phase.phase_id] = artifacts
        ctx.artifact_ids.extend(a.id for a in artifacts)

    # Workspace is now destroyed (stateless)
```

## Milestones

### Milestone 1: Agent Runner Package (4h)
- [ ] Create `packages/syn-agent-runner/`
- [ ] Implement task parsing from JSON
- [ ] Implement JSONL event output
- [ ] Add tests

### Milestone 2: Workspace Image Update (2h)
- [ ] Update `docker/workspace/Dockerfile`
- [ ] Add syn-agent-runner to image
- [ ] Test image build

### Milestone 3: Streaming Execution (4h)
- [ ] Add `execute_streaming` to workspace protocol
- [ ] Implement for Docker backend
- [ ] Add stdout line parsing

### Milestone 4: Engine Integration (4h)
- [ ] Update `_execute_phase` to use workspace
- [ ] Implement task preparation
- [ ] Implement event handling
- [ ] Update aggregate with events

### Milestone 5: E2E Test (2h)
- [ ] Test full workflow with isolation
- [ ] Verify artifacts collected
- [ ] Verify events persisted

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SDK compatibility | High | Test with claude-agent-sdk in container |
| Event streaming latency | Medium | Use line-buffered stdout |
| Image size | Low | Multi-stage build, slim base |
| Credential injection | High | Use token vending service (ADR-023) |

## Success Criteria

1. ✅ Agent process runs INSIDE workspace container
2. ✅ Orchestrator NEVER holds raw API keys
3. ✅ Events stream in real-time to aggregate
4. ✅ Resource limits enforced (CPU, memory)
5. ✅ Network restricted to allowlist
6. ✅ All existing tests pass

## Estimated Effort

| Milestone | Effort |
|-----------|--------|
| Agent Runner Package | 4h |
| Workspace Image | 2h |
| Streaming Execution | 4h |
| Engine Integration | 4h |
| E2E Test | 2h |
| **Total** | **16h** |

## Next Steps

1. Review and approve this plan
2. Create GitHub issue for tracking
3. Start with Milestone 1: Agent Runner Package
