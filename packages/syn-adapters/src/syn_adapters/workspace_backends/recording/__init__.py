"""Recording-based workspace adapters for integration testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

Replays pre-recorded agent sessions through Syn137's event pipeline,
enabling integration testing without API calls.

Usage:
    from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter
    from syn_adapters.workspace_backends.service import WorkspaceService

    adapter = RecordingEventStreamAdapter("simple-bash")
    service = WorkspaceService.create_test(event_stream=adapter)

    async with service.create_workspace(execution_id="test") as ws:
        async for line in ws.stream(["claude", "-p", "test"]):
            # Events from recording, no API calls
            process_event(line)

See ADR-033 (Recording-Based Integration Testing).
"""

from syn_adapters.workspace_backends.recording.adapter import (
    RecordingEventStreamAdapter,
)

__all__ = [
    "RecordingEventStreamAdapter",
]
