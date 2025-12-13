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

Execute agents **inside** the workspace container/VM, not in the host process.

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator (Host)                       │
│                                                              │
│  ┌──────────────────┐     ┌──────────────────────────────┐  │
│  │ WorkflowExecution │     │      Isolated Workspace       │  │
│  │     Engine        │────▶│  ┌────────────────────────┐  │  │
│  │                   │     │  │     Agent Process       │  │  │
│  │  - Start/Stop    │     │  │  - claude-agent-sdk     │  │  │
│  │  - Stream Events  │     │  │  - File access          │  │  │
│  │  - Collect Artifacts│   │  │  - API keys injected    │  │  │
│  └──────────────────┘     │  └────────────────────────┘  │  │
│                            │                              │  │
│                            │  Resource Limits:            │  │
│                            │  - 512MB RAM, 0.5 CPU        │  │
│                            │  - Network allowlist only    │  │
│                            └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
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
            "python", "-m", "aef_agent_runner",
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
- Need to package `aef_agent_runner` in workspace image
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

Create `packages/aef-agent-runner/` - a minimal package that:
1. Reads task from JSON file
2. Executes via `claude-agent-sdk`
3. Writes events to stdout (JSONL)
4. Writes artifacts to output dir

```python
# aef_agent_runner/__main__.py
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
RUN pip install aef-agent-runner

# Entry point
ENTRYPOINT ["python", "-m", "aef_agent_runner"]
```

### Phase 3: Engine Integration

Update `WorkflowExecutionEngine._execute_phase`:

```python
async def _execute_phase(
    self,
    workflow: Workflow,
    phase: WorkflowPhase,
    ctx: ExecutionContext,
    aggregate: WorkflowExecutionAggregate,
) -> None:
    # Create workspace config
    config = IsolatedWorkspaceConfig(
        base_config=WorkspaceConfig(session_id=ctx.execution_id),
        security=self._get_security_settings(phase),
    )
    
    # Create isolated workspace
    async with self._router.create(config) as workspace:
        # Inject task and credentials
        task_data = self._prepare_task(phase, ctx)
        await workspace.inject_context(
            files=[("task.json", json.dumps(task_data).encode())],
        )
        
        # Execute agent in workspace
        process = await workspace.execute_streaming([
            "python", "-m", "aef_agent_runner",
            "--task", "/workspace/task.json",
            "--output", "/workspace/output",
        ])
        
        # Stream events from stdout
        async for line in process.stdout:
            event = json.loads(line)
            # Update aggregate with event
            self._handle_agent_event(event, aggregate)
        
        # Wait for completion
        exit_code = await process.wait()
        
        # Collect artifacts
        artifacts = await workspace.collect_artifacts()
        ctx.artifact_ids.extend(a.id for a in artifacts)
```

## Milestones

### Milestone 1: Agent Runner Package (4h)
- [ ] Create `packages/aef-agent-runner/`
- [ ] Implement task parsing from JSON
- [ ] Implement JSONL event output
- [ ] Add tests

### Milestone 2: Workspace Image Update (2h)
- [ ] Update `docker/workspace/Dockerfile`
- [ ] Add aef-agent-runner to image
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
