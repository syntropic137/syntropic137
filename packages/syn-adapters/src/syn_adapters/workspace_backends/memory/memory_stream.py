"""In-memory event stream adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration import (
    COMMAND_TAIL_BYTES,
    BoundedCommandResult,
    CommandTerminal,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

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
        # isolation_id -> the result each `sh -c <run>` returns, by its run line.
        self._bounded: dict[str, dict[str, BoundedCommandResult]] = {}
        #: Every bounded command run, in order, as (isolation_id, argv).
        self.bounded_runs: list[tuple[str, list[str]]] = []

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call. Always 0 for mock."""
        return self._last_exit_code

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> AsyncIterator[str]:
        """Stream mock output lines.

        Args:
            handle: Isolation handle
            command: Command to execute (ignored)
            timeout_seconds: Timeout (ignored)
            wrapper_name: Launch announcement name (ignored - no process is
                created here, so there is nothing that could honestly answer
                to it, and the session is left UNKNOWN)
            withheld: Credential values to scrub (ignored - these lines are
                configured by a test, not printed by a workload)

        Yields:
            Pre-configured output lines
        """
        del (
            command,
            timeout_seconds,
            working_directory,
            environment,
            wrapper_name,
            withheld,
        )  # named for the port; unused here
        lines = self._streams.get(handle.isolation_id, [])
        for line in lines:
            yield line
        self._last_exit_code = 0

    async def run_bounded(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        tail_bytes: int = COMMAND_TAIL_BYTES,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> BoundedCommandResult:
        """The configured result for this command's run line, else a clean exit 0."""
        del timeout_seconds, working_directory, environment, tail_bytes, withheld
        self.bounded_runs.append((handle.isolation_id, list(command)))
        configured = self._bounded.get(handle.isolation_id, {})
        return configured.get(
            command[-1],
            BoundedCommandResult(terminal=CommandTerminal.EXITED, exit_code=0, duration_ms=0),
        )

    def set_bounded_result(
        self, handle: IsolationHandle, run: str, result: BoundedCommandResult
    ) -> None:
        """Configure what ``run_bounded`` returns for the step whose ``run`` is ``run``."""
        self._bounded.setdefault(handle.isolation_id, {})[run] = result

    async def cancel_running(self, handle: IsolationHandle) -> bool:
        """Nothing to cancel: no process is created here."""
        del handle
        return False

    def set_stream_output(self, handle: IsolationHandle, lines: list[str]) -> None:
        """Configure stream output for testing.

        Args:
            handle: Isolation handle
            lines: Lines to yield when stream() is called
        """
        self._streams[handle.isolation_id] = lines
