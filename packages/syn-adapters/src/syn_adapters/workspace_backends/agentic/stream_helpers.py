"""Stream helper functions for AgenticEventStreamAdapter.

Extracted from stream_adapter.py to reduce module cognitive complexity.
Handles process management and line-reading for docker exec streaming.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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


def _is_stream_timed_out(
    stream_timeout: float | None,
    start_time: float,
) -> bool:
    """Return True and log if the stream timeout has been reached."""
    if stream_timeout is None:
        return False
    elapsed = time.monotonic() - start_time
    if elapsed >= stream_timeout:
        logger.warning("Stream timed out after %.1fs", elapsed)
        return True
    return False


async def read_lines(
    proc: asyncio.subprocess.Process,
    stream_timeout: float | None,
    start_time: float,
) -> AsyncIterator[str]:
    """Read and yield decoded lines from process stdout."""
    while True:
        if _is_stream_timed_out(stream_timeout, start_time):
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
