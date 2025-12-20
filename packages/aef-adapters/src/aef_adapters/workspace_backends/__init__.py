"""Workspace backends - implementations of workspace ports.

This package contains adapter implementations for the workspace bounded context:
- memory/: In-memory adapters for testing (TEST ENVIRONMENT ONLY)
- docker/: Docker-based adapters for development/production
- recording/: Recording playback for integration testing (TEST ENVIRONMENT ONLY)
- firecracker/: Firecracker VM adapters for production (future)
- cloud/: Cloud sandbox adapters (E2B, Modal) (future)

Usage:
    # For testing (APP_ENVIRONMENT=test only)
    from aef_adapters.workspace_backends.memory import MemoryIsolationAdapter

    # For integration testing with recordings (APP_ENVIRONMENT=test only)
    from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

    # For production
    from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
See ADR-033 (Recording-Based Integration Testing).
"""
