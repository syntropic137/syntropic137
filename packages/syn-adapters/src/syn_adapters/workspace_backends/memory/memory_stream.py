"""In-memory event stream adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.memory.memory_adapter import _assert_test_environment

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )


class MemoryEventStreamAdapter:
    """In-memory implementation of EventStreamPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates event streaming with configurable output.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
        self._streams: dict[str, list[str]] = {}  # isolation_id -> lines
        self._last_exit_code: int | None = None

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call. Always 0 for mock."""
        return self._last_exit_code

    async def stream(
        self,
        handle: IsolationHandle,
        _command: list[str],
        *,
        _timeout_seconds: int | None = None,
        _working_directory: str | None = None,
        _environment: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Stream mock output lines.

        Args:
            handle: Isolation handle
            command: Command to execute (ignored)
            timeout_seconds: Timeout (ignored)

        Yields:
            Pre-configured output lines
        """
        lines = self._streams.get(handle.isolation_id, [])
        for line in lines:
            yield line
        self._last_exit_code = 0

    def set_stream_output(self, handle: IsolationHandle, lines: list[str]) -> None:
        """Configure stream output for testing.

        Args:
            handle: Isolation handle
            lines: Lines to yield when stream() is called
        """
        self._streams[handle.isolation_id] = lines
