"""WorkspaceService - orchestrates workspace lifecycle.

This module provides the WorkspaceService facade that composes all workspace
adapters into a single, easy-to-use interface for the WorkflowExecutionEngine.

The service orchestrates:
- Container creation and destruction (via agentic_isolation)
- Setup phase with GitHub App token (ADR-024)
- Secret clearing before agent phase
- Event streaming
- State management (WorkspaceAggregate)

GitHub Authentication:
    GitHub authentication is EXCLUSIVELY via GitHub App installation tokens.
    No personal access tokens (GH_TOKEN) are supported. This:
    - Reduces cognitive load (one clear auth path)
    - Ensures consistent, auditable authentication
    - Provides short-lived, scoped tokens (1 hour TTL)

Usage:
    from aef_adapters.workspace_backends.service import (
        WorkspaceService,
        WorkspaceBackend,
        SetupPhaseSecrets,
    )

    # Production (Docker isolation)
    service = WorkspaceService.create()

    # Testing (in-memory mocks, requires APP_ENVIRONMENT=test)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

    async with service.create_workspace(config) as workspace:
        # Create secrets using GitHub App (required for production)
        secrets = await SetupPhaseSecrets.create()
        await workspace.run_setup_phase(secrets)

        # Agent runs WITHOUT access to raw secrets
        async for line in workspace.stream(["agent-runner"]):
            process(line)

See ADR-021, ADR-023, ADR-024 for architectural decisions.
"""

from aef_adapters.workspace_backends.service.workspace_service import (
    DEFAULT_SETUP_SCRIPT,
    GitHubAppNotConfiguredError,
    ManagedWorkspace,
    SetupPhaseSecrets,
    WorkspaceBackend,
    WorkspaceService,
    WorkspaceServiceConfig,
)

__all__ = [
    "DEFAULT_SETUP_SCRIPT",
    "GitHubAppNotConfiguredError",
    "ManagedWorkspace",
    "SetupPhaseSecrets",
    "WorkspaceBackend",
    "WorkspaceService",
    "WorkspaceServiceConfig",
]
