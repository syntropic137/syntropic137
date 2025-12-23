"""Workspace backends - implementations of workspace ports.

This package contains adapter implementations for the workspace bounded context:
- agentic/: New adapters using agentic_isolation from agentic-primitives (RECOMMENDED)
- memory/: In-memory adapters for testing (TEST ENVIRONMENT ONLY)
- docker/: Docker-based adapters for development/production (DEPRECATED - use agentic/)
- recording/: Recording playback for integration testing (TEST ENVIRONMENT ONLY)
- firecracker/: Firecracker VM adapters for production (future)
- cloud/: Cloud sandbox adapters (E2B, Modal) (future)

Usage:
    # Recommended: Use agentic_isolation adapters
    from aef_adapters.workspace_backends.agentic import AgenticIsolationAdapter

    # For testing (APP_ENVIRONMENT=test only)
    from aef_adapters.workspace_backends.memory import MemoryIsolationAdapter

    # For integration testing with recordings (APP_ENVIRONMENT=test only)
    from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

    # Deprecated: Direct Docker adapters
    from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
See ADR-033 (Recording-Based Integration Testing).
"""
