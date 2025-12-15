# ⚠️ DEPRECATED MODULE - READY FOR DELETION

**Status**: ✅ Migration COMPLETE
**Action**: Delete this entire directory
**Replacement**: `aef_adapters.workspace_backends.service.WorkspaceService`

## Migration Complete

The new workspace bounded context has been implemented:

- ✅ Event-sourced `WorkspaceAggregate` in domain layer
- ✅ Clean port interfaces for DI (`IsolationBackendPort`, `SidecarPort`, etc.)
- ✅ Docker adapters (`DockerIsolationAdapter`, `DockerSidecarAdapter`)
- ✅ Token injection via sidecar per ADR-022
- ✅ `WorkspaceService` facade for easy usage
- ✅ `WorkflowExecutionEngine` migrated to new architecture
- ✅ 110 tests passing

## Why This Module Was Deprecated

### Architecture Problems (Fixed in New Implementation)

| Issue | Old Location | New Solution |
|-------|----------|--------|
| Fat orchestrator | `router.py` (789 lines) | `WorkspaceService` facade + adapters |
| Mixed concerns | Router did git, env, logging | Clean port/adapter separation |
| Sidecar not integrated | `sidecar.py` unused | `DockerSidecarAdapter` fully integrated |
| Token vending disconnected | No sidecar injection | `SidecarTokenInjectionAdapter` |
| No domain model | Just dataclasses | Event-sourced `WorkspaceAggregate` |
| Events not persisted | Events lost | Full event sourcing with audit trail |

## New Pattern (Use This)

```python
from aef_adapters.workspace_backends.service import WorkspaceService

# Production (Docker)
service = WorkspaceService.create_docker()

# Testing (in-memory)
service = WorkspaceService.create_memory()

# Usage
async with service.create_workspace(
    execution_id="exec-123",
    workflow_id="wf-456",
    inject_tokens=True,  # Auto-injects via sidecar
) as workspace:
    # Execute commands
    result = await workspace.execute(["python", "script.py"])
    
    # Stream agent output
    async for line in workspace.stream(["python", "-m", "aef_agent_runner"]):
        event = json.loads(line)
        handle_event(event)
    
    # Inject/collect files
    await workspace.inject_files([("task.json", task_data)])
    artifacts = await workspace.collect_files(["artifacts/**/*"])
```

## Files to Delete

All files in this directory should be deleted:

- `base.py` → Replaced by `aef_adapters.workspace_backends.*`
- `docker_hardened.py` → Replaced by `workspace_backends/docker/`
- `gvisor.py` → Replaced by `workspace_backends/docker/`
- `firecracker.py` → Future: `workspace_backends/firecracker/`
- `e2b.py` → Future: `workspace_backends/cloud/`
- `router.py` → Replaced by `WorkspaceService`
- `sidecar.py` → Replaced by `workspace_backends/docker/docker_sidecar_adapter.py`
- `git.py` → Future: configure_git slice
- `env_injector.py` → Replaced by `workspace_backends/tokens/`
- `network.py` → Integrated into sidecar adapter
- `contract.py` → Replaced by domain validation in aggregate

## Completed Timeline

1. ✅ Deprecation notice added
2. ✅ New workspace bounded context implemented
3. ✅ WorkflowExecutionEngine migrated to new context
4. ✅ 110 tests passing
5. 🔜 Delete this module (next step)

## Questions?

See:
- `docs/adrs/ADR-021-isolated-workspace-architecture.md`
- `docs/adrs/ADR-022-secure-token-architecture.md`
- `docs/adrs/ADR-023-workspace-first-execution-model.md`
