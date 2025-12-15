"""Docker event stream adapter for real-time stdout streaming.

Implements EventStreamPort for streaming command output from Docker containers.

This is used to capture agent runner JSONL events in real-time for:
- Observability and logging
- Cost tracking
- Progress monitoring
- Error detection

See ADR-015: Agent Observability
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_domain.contexts.workspaces._shared.value_objects import IsolationHandle

logger = logging.getLogger(__name__)


class DockerEventStreamAdapter:
    """Docker implementation of EventStreamPort.

    Streams stdout from docker exec commands line by line.

    Usage:
        adapter = DockerEventStreamAdapter()

        async for line in adapter.stream(
            handle,
            ["python", "-u", "agent_runner.py"],
        ):
            event = json.loads(line)
            process_event(event)
    """

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

        Yields lines as they are produced by the command.
        Uses docker exec with attached stdout.

        Args:
            handle: Isolation handle (container ID)
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Yields:
            Individual stdout lines (without newlines)

        Raises:
            RuntimeError: If streaming fails to start
        """
        # Build docker exec command
        exec_cmd = ["docker", "exec", "-i"]  # -i for interactive (stdin attached)

        # Working directory
        if working_directory:
            exec_cmd.extend(["-w", working_directory])
        else:
            exec_cmd.extend(["-w", "/workspace"])

        # Environment variables
        if environment:
            for key, value in environment.items():
                exec_cmd.extend(["-e", f"{key}={value}"])

        # Container ID and command
        exec_cmd.append(handle.isolation_id)
        exec_cmd.extend(command)

        logger.info(
            "Starting stream (container=%s, cmd=%s)",
            handle.isolation_id[:12],
            " ".join(command[:3]) + ("..." if len(command) > 3 else ""),
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            if proc.stdout is None:
                raise RuntimeError("Failed to attach to stdout")

            # Stream lines with optional timeout
            try:
                async for line in self._stream_lines(proc, timeout_seconds):
                    yield line
            finally:
                # Ensure process is terminated
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except TimeoutError:
                        proc.kill()

            # Check exit code
            if proc.returncode != 0 and proc.returncode is not None:
                stderr = ""
                if proc.stderr:
                    stderr_data = await proc.stderr.read()
                    stderr = stderr_data.decode()
                logger.warning(
                    "Stream command exited with code %d: %s",
                    proc.returncode,
                    stderr[:200] if stderr else "(no stderr)",
                )

        except Exception as e:
            logger.exception("Stream error (container=%s): %s", handle.isolation_id[:12], e)
            raise

    async def _stream_lines(
        self,
        proc: asyncio.subprocess.Process,
        timeout_seconds: int | None,
    ) -> AsyncIterator[str]:
        """Stream lines from process stdout with timeout.

        Args:
            proc: Running subprocess
            timeout_seconds: Total timeout (None = no timeout)

        Yields:
            Individual lines without trailing newline
        """
        assert proc.stdout is not None

        start_time = asyncio.get_event_loop().time()

        while True:
            # Check timeout
            if timeout_seconds:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout_seconds:
                    logger.warning("Stream timeout after %.1fs", elapsed)
                    break

                remaining = timeout_seconds - elapsed
            else:
                remaining = None

            try:
                # Read with timeout
                if remaining is not None:
                    line_bytes = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=remaining,
                    )
                else:
                    line_bytes = await proc.stdout.readline()

                if not line_bytes:
                    # EOF
                    break

                line = line_bytes.decode().rstrip("\n")
                yield line

            except TimeoutError:
                logger.warning("Stream read timeout")
                break
            except Exception as e:
                logger.warning("Stream read error: %s", e)
                break

    async def stream_stderr(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream stderr lines from command execution.

        Similar to stream() but yields stderr instead.
        Useful for error monitoring.

        Args:
            handle: Isolation handle
            command: Command to execute
            timeout_seconds: Max execution time

        Yields:
            Individual stderr lines
        """
        exec_cmd = [
            "docker",
            "exec",
            "-i",
            "-w",
            "/workspace",
            handle.isolation_id,
            *command,
        ]

        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if proc.stderr is None:
            return

        try:
            async for line in self._stream_lines_from(proc.stderr, timeout_seconds):
                yield line
        finally:
            if proc.returncode is None:
                proc.terminate()

    async def _stream_lines_from(
        self,
        stream: asyncio.StreamReader,
        timeout_seconds: int | None,
    ) -> AsyncIterator[str]:
        """Stream lines from a stream reader."""
        start_time = asyncio.get_event_loop().time()

        while True:
            if timeout_seconds:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout_seconds:
                    break
                remaining = timeout_seconds - elapsed
            else:
                remaining = None

            try:
                if remaining is not None:
                    line_bytes = await asyncio.wait_for(
                        stream.readline(),
                        timeout=remaining,
                    )
                else:
                    line_bytes = await stream.readline()

                if not line_bytes:
                    break

                yield line_bytes.decode().rstrip("\n")

            except TimeoutError:
                break
