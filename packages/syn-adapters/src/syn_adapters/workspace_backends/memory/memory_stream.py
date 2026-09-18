"""In-memory event stream adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )


class MemoryEventStreamAdapter(InMemoryAdapter):
    """In-memory implementation of EventStreamPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates event streaming with configurable output.
    Inherits environment guard from InMemoryAdapter.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        super().__init__()
        self._streams: dict[str, list[str]] = {}  # isolation_id -> lines
        self._last_exit_code: int | None = None

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call. Always 0 for mock."""
        return self._last_exit_code

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],  # noqa: ARG002
        *,
        timeout_seconds: int | None = None,  # noqa: ARG002
        working_directory: str | None = None,  # noqa: ARG002
        environment: dict[str, str] | None = None,  # noqa: ARG002
        wrapper_name: str | None = None,  # noqa: ARG002
    ) -> AsyncIterator[str]:
        """Stream mock output lines.

        The unused parameters are named as `EventStreamPort` names them, with
        `noqa` rather than an underscore prefix, because `ManagedWorkspace`
        passes them BY KEYWORD: an underscore-prefixed parameter is a different
        keyword, so this adapter could not be streamed through at all
        (`TypeError: unexpected keyword argument 'timeout_seconds'`). The
        recording adapter beside it already spells them this way.

        Args:
            handle: Isolation handle
            command: Command to execute (ignored)
            timeout_seconds: Timeout (ignored)
            wrapper_name: Launch announcement name (ignored - no process is
                created here, so there is nothing that could honestly answer
                to it, and the session is left UNKNOWN)

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
