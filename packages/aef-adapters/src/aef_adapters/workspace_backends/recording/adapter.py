"""Recording event stream adapter for integration testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

Replays pre-recorded agent sessions through AEF's event pipeline.
This enables integration testing of the full event flow without API calls.

See ADR-033: Recording-Based Integration Testing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentic_events import SessionPlayer
    from agentic_events.player import RecordingMetadata

    from aef_domain.contexts.workspaces._shared.value_objects import IsolationHandle


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
    if app_env in ("test", "testing"):
        return

    raise RecordingAdapterTestOnlyError(
        "RecordingEventStreamAdapter can only be used in tests. "
        "Either run via pytest or set APP_ENVIRONMENT=test."
    )


class RecordingEventStreamAdapter:
    """Event stream adapter that replays recorded sessions.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Enables integration testing of the full AEF event pipeline
    using pre-recorded agent sessions, without spending tokens.

    This adapter implements the EventStreamPort protocol and can be
    passed to WorkspaceService.create_test() to replace the real
    Docker event stream with recorded events.

    Usage:
        # Load recording by task name
        adapter = RecordingEventStreamAdapter("simple-bash")

        # Use with WorkspaceService
        service = WorkspaceService.create_test(event_stream=adapter)

        async with service.create_workspace(execution_id="test") as ws:
            async for line in ws.stream(["claude", "-p", "test"]):
                # Events replay from recording
                process_event(line)

    Attributes:
        metadata: Recording metadata (cli_version, model, duration, etc.)
        event_count: Number of events in the recording

    See Also:
        - agentic_events.SessionPlayer: The underlying player
        - agentic_events.load_recording: Helper to load recordings
        - ADR-033: Recording-Based Integration Testing
    """

    _player: SessionPlayer
    _realtime: bool
    _speed: float

    def __init__(
        self,
        recording: str | Path | SessionPlayer,
        *,
        realtime: bool = False,
        speed: float = 1.0,
    ) -> None:
        """Initialize with a recording.

        Args:
            recording: One of:
                - Task name (e.g., "simple-bash") - loads from fixtures
                - Path to recording file
                - SessionPlayer instance
            realtime: If True, replay with original timing delays.
                     If False (default), yield all events instantly.
            speed: Playback speed multiplier when realtime=True.
                   1.0 = real-time, 10.0 = 10x faster, etc.

        Raises:
            TestEnvironmentRequiredError: If not in test environment
            FileNotFoundError: If recording doesn't exist

        Examples:
            # Load by task name (finds in fixtures)
            adapter = RecordingEventStreamAdapter("simple-bash")

            # Load from specific path
            adapter = RecordingEventStreamAdapter(Path("my-recording.jsonl"))

            # Real-time replay at 100x speed
            adapter = RecordingEventStreamAdapter("multi-tool", realtime=True, speed=100)
        """
        _assert_test_environment()

        # Import here to avoid import errors when agentic-events not installed
        from agentic_events import SessionPlayer, load_recording

        if isinstance(recording, SessionPlayer):
            self._player = recording
        elif isinstance(recording, Path):
            self._player = SessionPlayer(recording)
        else:
            # Assume it's a task name string
            self._player = load_recording(str(recording))

        self._realtime = realtime
        self._speed = speed

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
