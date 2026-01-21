"""Port interface for workspace lifecycle management.

Per ADR-023: Workspace-First Execution Model, agents MUST run inside isolated
workspaces. This port defines the contract for workspace creation and management.
"""

from typing import TYPE_CHECKING, AsyncContextManager, Protocol

if TYPE_CHECKING:
    from aef_adapters.workspace_backends.service import ManagedWorkspace


class WorkspaceServicePort(Protocol):
    """Domain service port for workspace lifecycle management.

    Per ADR-021 (Isolated Workspace Architecture) and ADR-023 (Workspace-First
    Execution Model), agents execute inside isolated environments (Docker containers,
    Firecracker VMs, etc.).

    This port abstracts the workspace backend implementation details, allowing:
    - Docker isolation (default)
    - Firecracker VMs (future)
    - gVisor sandboxing (future)
    - Local workspace (test only)
    """

    def create_workspace(
        self,
        execution_id: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        with_sidecar: bool = False,
        inject_tokens: bool = False,
    ) -> AsyncContextManager["ManagedWorkspace"]:
        """Create an isolated workspace for agent execution.

        The workspace provides:
        - Isolated filesystem (mounted from host)
        - Setup phase for secrets (ADR-024)
        - Artifact injection/collection (ADR-036)
        - Event streaming (ADR-029)

        Args:
            execution_id: The execution ID for this workspace.
            workflow_id: Optional workflow ID for context.
            phase_id: Optional phase ID for context.
            with_sidecar: Whether to start token vending sidecar (deprecated - use setup phase).
            inject_tokens: Whether to inject tokens (deprecated - use setup phase).

        Returns:
            AsyncContextManager that yields ManagedWorkspace.
            The workspace is automatically destroyed on context exit.

        Example:
            async with workspace_service.create_workspace(execution_id="exec-123") as ws:
                # Run setup phase with secrets (ADR-024)
                await ws.run_setup_phase(secrets)

                # Execute agent
                async for line in ws.stream(["claude", "-p", "Hello"]):
                    process_event(line)

                # Collect artifacts
                artifacts = await ws.collect_files(patterns=["artifacts/output/**/*"])
            # Workspace destroyed here
        """
        ...
