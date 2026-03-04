"""Recording event stream adapter for integration testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

Replays pre-recorded agent sessions through Syn137's event pipeline.
This enables integration testing of the full event flow without API calls.

Supports workspace file capture for testing artifact flow between phases.

See ADR-033: Recording-Based Integration Testing.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentic_events import Recording, SessionPlayer
    from agentic_events.player import RecordingMetadata

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )


class RecordingAdapterTestOnlyError(RuntimeError):
    """Raised when recording adapter is used outside test environment."""

    pass


def _assert_test_environment() -> None:
    """Raise if not in test environment.

    Recording adapters should only be used in tests to prevent
    accidental use of recorded data in production.
    """
    # Check for pytest
    if os.environ.get("PYTEST_CURRENT_TEST") is not None:
        return

    # Check for APP_ENVIRONMENT
    app_env = os.environ.get("APP_ENVIRONMENT", "").lower()
    if app_env in ("test", "testing", "offline"):
        return

    raise RecordingAdapterTestOnlyError(
        "RecordingEventStreamAdapter can only be used in tests. "
        "Either run via pytest or set APP_ENVIRONMENT=test."
    )


class RecordingEventStreamAdapter:
    """Event stream adapter that replays recorded sessions.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Enables integration testing of the full Syn137 event pipeline
    using pre-recorded agent sessions, without spending tokens.

    This adapter implements the EventStreamPort protocol and can be
    passed to WorkspaceService.create_test() to replace the real
    Docker event stream with recorded events.

    Also provides workspace files for testing artifact collection.

    Usage:
        # Type-safe loading with Recording enum
        from agentic_events import Recording
        adapter = RecordingEventStreamAdapter(Recording.SIMPLE_BASH)

        # Load recording by task name (string)
        adapter = RecordingEventStreamAdapter("simple-bash")

        # Use with WorkspaceService
        service = WorkspaceService.create_test(event_stream=adapter)

        async with service.create_workspace(execution_id="test") as ws:
            async for line in ws.stream(["claude", "-p", "test"]):
                # Events replay from recording
                process_event(line)

            # Collect workspace files from recording
            files = adapter.collect_files(patterns=["artifacts/output/**/*"])

    Attributes:
        metadata: Recording metadata (cli_version, model, duration, etc.)
        event_count: Number of events in the recording
        has_workspace: True if recording includes workspace files

    See Also:
        - agentic_events.SessionPlayer: The underlying player
        - agentic_events.Recording: Type-safe recording names
        - agentic_events.load_recording: Helper to load recordings
        - ADR-033: Recording-Based Integration Testing
    """

    _player: SessionPlayer
    _realtime: bool
    _speed: float

    def __init__(
        self,
        recording: Recording | str | Path | SessionPlayer,
        *,
        realtime: bool = False,
        speed: float = 1.0,
    ) -> None:
        """Initialize with a recording.

        Args:
            recording: One of:
                - Recording enum (e.g., Recording.SIMPLE_BASH) - type-safe
                - Task name string (e.g., "simple-bash") - loads from fixtures
                - Path to recording file or directory
                - SessionPlayer instance
            realtime: If True, replay with original timing delays.
                     If False (default), yield all events instantly.
            speed: Playback speed multiplier when realtime=True.
                   1.0 = real-time, 10.0 = 10x faster, etc.

        Raises:
            TestEnvironmentRequiredError: If not in test environment
            FileNotFoundError: If recording doesn't exist

        Examples:
            # Type-safe with enum (recommended)
            from agentic_events import Recording
            adapter = RecordingEventStreamAdapter(Recording.SIMPLE_BASH)

            # Load by task name (backward compatible)
            adapter = RecordingEventStreamAdapter("simple-bash")

            # Load from specific path
            adapter = RecordingEventStreamAdapter(Path("my-recording.jsonl"))

            # Real-time replay at 100x speed
            adapter = RecordingEventStreamAdapter(Recording.MULTI_TOOL, realtime=True, speed=100)
        """
        _assert_test_environment()

        # Import here to avoid import errors when agentic-events not installed
        from agentic_events import Recording, SessionPlayer, load_recording

        if isinstance(recording, SessionPlayer):
            self._player = recording
        elif isinstance(recording, Path):
            self._player = SessionPlayer(recording)
        elif isinstance(recording, Recording):
            # Type-safe enum - use directly
            self._player = load_recording(recording)
        else:
            # Assume it's a task name string
            self._player = load_recording(str(recording))

        self._realtime = realtime
        self._speed = speed
        self._last_exit_code: int | None = None

    async def stream(
        self,
        handle: IsolationHandle,  # noqa: ARG002
        command: list[str],  # noqa: ARG002
        *,
        timeout_seconds: int | None = None,  # noqa: ARG002
        working_directory: str | None = None,  # noqa: ARG002
        environment: dict[str, str] | None = None,  # noqa: ARG002
    ) -> AsyncIterator[str]:
        """Stream events from recording.

        Yields JSONL lines matching what Docker would emit.
        The command and other parameters are ignored since we're
        replaying a pre-recorded session.

        Args:
            handle: Isolation handle (ignored - using recorded session)
            command: Command to execute (ignored)
            timeout_seconds: Timeout (ignored)
            working_directory: Working directory (ignored)
            environment: Environment variables (ignored)

        Yields:
            JSONL event strings, one per line
        """
        if self._realtime:
            # Replay with timing delays
            async for event, _delay in self._player.play_async(speed=self._speed):
                yield json.dumps(event)
        else:
            # Instant replay - yield all events immediately
            for event in self._player:
                yield json.dumps(event)
        self._last_exit_code = 0

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call. Always 0 for recordings."""
        return self._last_exit_code

    @property
    def metadata(self) -> RecordingMetadata | None:
        """Recording metadata.

        Returns:
            RecordingMetadata with cli_version, model, duration_ms, etc.
        """
        return self._player.metadata

    @property
    def event_count(self) -> int:
        """Number of events in recording."""
        return len(self._player)

    @property
    def session_id(self) -> str | None:
        """Session ID from the recording."""
        return self._player.session_id

    def get_events(self) -> list[dict[str, Any]]:
        """Get all events from the recording.

        Useful for assertions in tests.

        Returns:
            List of event dictionaries
        """
        return self._player.get_events()

    @property
    def has_workspace(self) -> bool:
        """True if recording includes workspace files.

        Workspace files are available in directory-format recordings
        that captured the agent's output after execution.
        """
        return self._player.has_workspace

    def get_workspace_files(self) -> dict[str, bytes]:
        """Get all workspace files from the recording.

        Returns:
            Dict mapping relative path -> file content.
            e.g., {"artifacts/output/summary.md": b"# Summary..."}

        Returns empty dict for recordings without workspace files.
        """
        return self._player.get_workspace_files()

    def collect_files(
        self,
        patterns: list[str] | None = None,
    ) -> list[tuple[str, bytes]]:
        """Collect files matching patterns from the recording's workspace.

        This mimics the behavior of ManagedWorkspace.collect_files() but
        returns files from the recording instead of a real container.

        Args:
            patterns: Glob patterns to match (default: ["artifacts/**/*"])

        Returns:
            List of (relative_path, content) tuples matching the patterns.

        Examples:
            >>> adapter = RecordingEventStreamAdapter(Recording.ARTIFACT_WORKFLOW)
            >>> files = adapter.collect_files(patterns=["artifacts/output/**/*"])
            >>> for path, content in files:
            ...     print(f"{path}: {len(content)} bytes")
        """
        pats = patterns or ["artifacts/**/*"]
        workspace_files = self.get_workspace_files()

        results: list[tuple[str, bytes]] = []
        for file_path, content in workspace_files.items():
            for pattern in pats:
                if fnmatch.fnmatch(file_path, pattern):
                    results.append((file_path, content))
                    break  # Don't add same file twice

        return results
