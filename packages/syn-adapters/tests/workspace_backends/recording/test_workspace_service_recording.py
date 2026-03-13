"""Tests for WorkspaceService.create_recording() factory.

Validates that recording-backed WorkspaceService creates workspaces
that stream events from pre-recorded sessions.
"""

from __future__ import annotations

import json

import pytest

from agentic_events import Recording
from syn_adapters.workspace_backends.service import WorkspaceService

pytestmark = [pytest.mark.unit, pytest.mark.integration]


class TestWorkspaceServiceRecording:
    """Tests for the recording backend factory."""

    def test_create_recording_returns_service(self) -> None:
        """create_recording() returns a configured WorkspaceService."""
        try:
            service = WorkspaceService.create_recording(Recording.SIMPLE_BASH)
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        assert isinstance(service, WorkspaceService)

    @pytest.mark.asyncio
    async def test_create_workspace_streams_recording_events(self) -> None:
        """Workspace created from recording streams valid JSONL events."""
        try:
            service = WorkspaceService.create_recording(Recording.SIMPLE_BASH)
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        async with service.create_workspace(
            execution_id="test-recording",
            with_sidecar=False,
        ) as workspace:
            lines: list[str] = []
            async for line in workspace.stream(["claude", "-p", "test"]):
                parsed = json.loads(line)
                assert isinstance(parsed, dict)
                lines.append(line)

            assert len(lines) > 0, "Expected events from recording"

    @pytest.mark.asyncio
    async def test_create_recording_with_string_name(self) -> None:
        """create_recording() accepts string recording names."""
        try:
            service = WorkspaceService.create_recording("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        async with service.create_workspace(
            execution_id="test-string",
            with_sidecar=False,
        ) as workspace:
            count = 0
            async for _line in workspace.stream(["test"]):
                count += 1
            assert count > 0

    @pytest.mark.asyncio
    async def test_stream_event_types_match_recording(self) -> None:
        """Streamed events have expected types from the recording."""
        try:
            service = WorkspaceService.create_recording(Recording.SIMPLE_BASH)
        except FileNotFoundError:
            pytest.skip("simple-bash recording not available")

        async with service.create_workspace(
            execution_id="test-types",
            with_sidecar=False,
        ) as workspace:
            event_types: set[str] = set()
            async for line in workspace.stream(["test"]):
                parsed = json.loads(line)
                if "type" in parsed:
                    event_types.add(parsed["type"])

            assert "system" in event_types, "Expected system event"
            assert "result" in event_types, "Expected result event"
