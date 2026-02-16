# workspaces

Isolated workspace management for workflow execution.

## create_workspace()

Create an isolated workspace (Docker container with egress proxy).

**Signature:**

```python
async def create_workspace(
    execution_id: str,
    workflow_id: str | None = None,
    phase_id: str | None = None,
    with_sidecar: bool = True,
    environment: dict[str, str] | None = None,
    auth: AuthContext | None = None,
) -> Result[str, WorkflowError]
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `execution_id` | `str` | required | Execution ID for this workspace |
| `workflow_id` | `str \| None` | `None` | Associated workflow |
| `phase_id` | `str \| None` | `None` | Associated phase |
| `with_sidecar` | `bool` | `True` | Start egress proxy sidecar |
| `environment` | `dict[str, str] \| None` | `None` | Extra environment variables |
| `auth` | `AuthContext \| None` | `None` | Optional auth context |

**Returns:** `Ok(workspace_id)` on success.

**Note:** For production use, prefer using `WorkspaceService.create_workspace()` directly as an async context manager for automatic cleanup.

---

## terminate_workspace()

Terminate an isolated workspace.

**Signature:**

```python
async def terminate_workspace(
    workspace_id: str,
    auth: AuthContext | None = None,
) -> Result[None, WorkflowError]
```

**Status:** Stub — workspaces are cleaned up automatically via the context manager pattern.
