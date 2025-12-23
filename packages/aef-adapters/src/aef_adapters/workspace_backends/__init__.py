"""Workspace backends - implementations of workspace ports.

This package contains adapter implementations for the workspace bounded context:
- service/: WorkspaceService facade (RECOMMENDED entry point)
- agentic/: Adapters using agentic_isolation from agentic-primitives
- memory/: In-memory adapters for testing (TEST ENVIRONMENT ONLY)
- docker/: Sidecar proxy adapter
- recording/: Recording playback for integration testing (TEST ENVIRONMENT ONLY)

Usage:
    from aef_adapters.workspace_backends.service import (
        WorkspaceService,
        WorkspaceBackend,
    )

    # Production (Docker isolation)
    service = WorkspaceService.create()

    # Testing (requires APP_ENVIRONMENT=test)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
See ADR-033 (Recording-Based Integration Testing).
"""
