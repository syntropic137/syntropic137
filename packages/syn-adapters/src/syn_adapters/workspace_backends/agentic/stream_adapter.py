"""Agentic event stream adapter - real-time stdout streaming for observability.

Separated from adapter.py for single-responsibility clarity.
See ADR-021: Isolated Workspace Architecture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from agentic_isolation import (
    WorkspaceDockerProvider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

logger = logging.getLogger(__name__)


def _build_exec_command(
    container_name: str,
    command: list[str],
    working_directory: str | None,
    environment: dict[str, str] | None,
) -> list[str]:
    """Build the docker exec command list."""
    exec_cmd = ["docker", "exec", "-i", "-w", working_directory or "/workspace"]
    if environment:
        for key, value in environment.items():
            exec_cmd.extend(["-e", f"{key}={value}"])
    exec_cmd.append(container_name)
    exec_cmd.extend(command)
    return exec_cmd


async def _cleanup_process(proc: asyncio.subprocess.Process) -> int | None:
    """Terminate/kill process and return exit code."""
    if proc.returncode is None:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (TimeoutError, ProcessLookupError):
            proc.kill()
    if proc.returncode is None:
        await proc.wait()
    return proc.returncode


class AgenticEventStreamAdapter:
    """Implements EventStreamPort using agentic_isolation streaming.

    This adapter provides real-time stdout streaming for observability.
    """

    def __init__(self) -> None:
        """Initialize the adapter."""
        self._provider: WorkspaceDockerProvider | None = None
        self._last_exit_code: int | None = None

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call.

        Returns None if no stream has completed yet.
        """
        return self._last_exit_code

    def set_provider(self, provider: WorkspaceDockerProvider) -> None:
        """Set the provider for streaming.

        Called by AgenticIsolationAdapter to share the provider.
        """
        self._provider = provider

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Stream stdout lines from command execution.

        Args:
            handle: Handle from isolation adapter
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Yields:
            Individual stdout lines as they are produced

        ARCHITECTURE NOTE — stderr=STDOUT is intentional (ADR-043):
        -----------------------------------------------------------------
        stderr=STDOUT merges any direct stderr from the claude CLI process into the
        stdout pipe so nothing is silently discarded (edge cases, internal errors).

        HOW GIT HOOK EVENTS ACTUALLY FLOW (important — not the obvious path):
        When Claude runs `git commit` via the Bash tool, the post-commit hook fires
        and emits JSONL to stderr. Claude Code captures Bash tool stderr as part of
        the tool output, then packages it inside a stream-json "user/tool_result"
        event. The JSONL arrives EMBEDDED inside tool_result content — NOT as a
        standalone raw line. WorkflowExecutionEngine scans each tool_result's full
        content string for embedded JSONL (see the tool_result branch in the loop).

        stderr=PIPE would silently discard any stderr escaping Claude Code's own
        packaging. Do not revert to PIPE or DEVNULL.

        IMPORTANT — TWO DOCKER EXEC PATHS EXIST. This file is the production path
        (used by the workspace service). agentic_isolation/providers/docker.py has
        the same fix but is only used in agentic_isolation contexts. Both must stay
        in sync — changing docker.py alone has no effect on the dashboard.
        """
        stream_timeout = float(timeout_seconds) if timeout_seconds else None
        if self._provider is None:
            raise RuntimeError("Provider not set. Call set_provider first.")

        container_name = f"agentic-ws-{handle.isolation_id.split('-')[1]}"
        exec_cmd = _build_exec_command(
            container_name, command, working_directory, environment,
        )

        logger.debug(
            "Starting stream (container=%s, cmd=%s, timeout=%s)",
            container_name, command, stream_timeout,
        )

        start_time = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=10 * 1024 * 1024,
        )

        try:
            async for line in self._read_lines(proc, stream_timeout, start_time):
                yield line
        finally:
            exit_code = await _cleanup_process(proc)
            self._last_exit_code = exit_code
            if exit_code and exit_code != 0:
                logger.warning(
                    "Stream process exited with code %d (container=%s)",
                    exit_code, container_name,
                )

    @staticmethod
    async def _read_lines(
        proc: asyncio.subprocess.Process,
        stream_timeout: float | None,
        start_time: float,
    ) -> AsyncIterator[str]:
        """Read and yield decoded lines from process stdout."""
        while True:
            if stream_timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= stream_timeout:
                    logger.warning("Stream timed out after %.1fs", elapsed)
                    break

            if proc.stdout is None:
                break

            try:
                line_bytes = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=1.0,
                )
            except TimeoutError:
                if proc.returncode is not None:
                    break
                continue

            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace").rstrip("\n\r")
            if line:
                yield line
