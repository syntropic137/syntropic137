"""Stream helper functions for AgenticEventStreamAdapter.

Extracted from stream_adapter.py to reduce module cognitive complexity.
Handles process management for docker exec streaming.
Line-reading is in stream_reader.py.
"""

from __future__ import annotations

import asyncio
import logging
import time

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
