"""Workspace operations — create and terminate isolated workspaces.

Maps to the orchestration context in aef-domain.
WorkspaceService uses an async context manager pattern — create_workspace
yields a ManagedWorkspace that is cleaned up on exit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_api._wiring import ensure_connected
from aef_api.types import Err, Ok, Result, WorkflowError

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


async def create_workspace(
    execution_id: str,
    workflow_id: str | None = None,
    phase_id: str | None = None,
    with_sidecar: bool = True,
    environment: dict[str, str] | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, WorkflowError]:
    """Create an isolated workspace for workflow execution.

    Note: WorkspaceService.create_workspace is an async context manager.
    This function creates the workspace but does NOT manage its lifecycle.
    For production use, prefer using WorkspaceService.create_workspace()
    directly as a context manager via aef_api._wiring.

    Args:
        execution_id: Execution ID for this workspace.
        workflow_id: Optional workflow this workspace is for.
        phase_id: Optional phase within the workflow.
        with_sidecar: Whether to start the egress proxy sidecar.
        environment: Optional extra environment variables.
        auth: Optional authentication context.

    Returns:
        Ok(workspace_id) on success, Err(WorkflowError) on failure.
    """
    from aef_adapters.workspace_backends.service import WorkspaceService

    await ensure_connected()
    try:
        service = WorkspaceService.create(environment=environment or {})
        # create_workspace is a context manager — we enter it and return the ID
        # The caller is responsible for cleanup in production usage
        ctx = service.create_workspace(
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            with_sidecar=with_sidecar,
        )
        workspace = await ctx.__aenter__()
        return Ok(workspace.workspace_id)
    except Exception as e:
        return Err(WorkflowError.EXECUTION_FAILED, message=f"Failed to create workspace: {e}")


async def terminate_workspace(
    workspace_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, WorkflowError]:
    """Terminate an isolated workspace.

    Note: In normal operation, workspaces are cleaned up automatically
    when the async context manager from create_workspace exits.
    This function provides explicit termination for edge cases.

    Args:
        workspace_id: The workspace to terminate.
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(WorkflowError) on failure.
    """
    # TODO(#92): Implement explicit workspace termination
    # WorkspaceService handles cleanup via context manager __aexit__,
    # but we may need a direct kill path for orphaned workspaces.
    return Err(
        WorkflowError.NOT_IMPLEMENTED,
        message=f"terminate_workspace({workspace_id}) not yet implemented — "
        "workspaces are cleaned up via context manager exit",
    )
