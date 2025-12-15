# ⚠️ DEPRECATED MODULE

**Status**: Migration in Progress
**Target Removal**: After new workspace bounded context is complete
**Migration Guide**: See `PROJECT-PLAN_20251215_WORKSPACE-BOUNDED-CONTEXT.md`

## Why This Module Is Deprecated

### Architecture Problems

| Issue | Location | Impact |
|-------|----------|--------|
| Fat orchestrator | `router.py` (789 lines) | Untestable, hard to understand |
| Mixed concerns | Router does git, env, logging, contracts | No separation of concerns |
| Sidecar not integrated | `sidecar.py` exists but unused | Security gap (ADR-022) |
| Token vending disconnected | `aef-tokens/` not wired to sidecar | Security gap (ADR-022) |
| No domain model | `IsolatedWorkspace` is just a dataclass | No invariants enforced |
| Events not persisted | Workspace events emitted but not sourced | No audit trail |

### ADR Violations

- **ADR-022 (Secure Token Architecture)**: Tokens are injected directly via env vars, not via sidecar proxy
- **ADR-021 (Isolated Workspace)**: Egress filtering not properly enforced
- **ADR-023 (Workspace-First)**: Events not persisted to event store

## Migration Path

### Old Pattern (Deprecated)

```python
from aef_adapters.workspaces import get_workspace_router

router = get_workspace_router()
async with router.create(config) as workspace:
    await router.execute_command(workspace, ["python", "script.py"])
    artifacts = await router.collect_artifacts(workspace)
```

### New Pattern (Use This)

```python
from aef_domain.contexts.workspaces import WorkspaceAggregate
from aef_domain.contexts.workspaces.create_workspace import CreateWorkspaceCommand
from aef_adapters.workspace_backends.docker import DockerIsolationAdapter
from aef_adapters.workspace_backends.memory import MemoryIsolationAdapter

# For testing (no Docker required)
adapter = MemoryIsolationAdapter()

# For production
adapter = DockerIsolationAdapter(docker_client)

# Create workspace via aggregate
aggregate = WorkspaceAggregate()
aggregate.handle(CreateWorkspaceCommand(
    execution_id="exec-123",
    isolation_backend="docker",
    capabilities=["network", "git"],
))

# Execute command
aggregate.handle(ExecuteCommandCommand(
    command=["python", "script.py"],
))

# Events are persisted to event store automatically
```

## Files to Delete (After Migration)

All files in this directory will be deleted:

- `base.py` → Replaced by `aef_adapters.workspace_backends.*`
- `docker_hardened.py` → Replaced by `workspace_backends/docker/`
- `gvisor.py` → Replaced by `workspace_backends/docker/`
- `firecracker.py` → Replaced by `workspace_backends/firecracker/`
- `e2b.py` → Replaced by `workspace_backends/cloud/`
- `router.py` → Replaced by `WorkspaceAggregate` + application handlers
- `sidecar.py` → Integrated into `workspace_backends/docker/sidecar_adapter.py`
- `git.py` → Replaced by `configure_git` slice
- `env_injector.py` → Replaced by `inject_tokens` slice + sidecar
- `network.py` → Integrated into sidecar adapter
- `contract.py` → Replaced by domain validation in aggregate

## Timeline

1. ✅ Deprecation notice added (this PR)
2. 🔄 New workspace bounded context implemented
3. ⏳ WorkflowExecutionEngine migrated to new context
4. ⏳ All tests migrated
5. ⏳ This module deleted

## Questions?

See `docs/adrs/ADR-021-isolated-workspace-architecture.md` for the target design.
