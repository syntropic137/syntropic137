"""Stream helper functions for AgenticEventStreamAdapter.

Extracted from stream_adapter.py to reduce module cognitive complexity.
Handles process management for docker exec streaming.
Line-reading is in stream_reader.py.
"""

from __future__ import annotations

import asyncio
import logging
import time

from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AGENT_LAUNCH_MARKER,
)

logger = logging.getLogger(__name__)

#: Announce the launch from inside the container, then become the agent.
#:
#: This is the only thing in the system that can emit the marker: reaching it
#: requires the daemon to have accepted the exec and created a process in the
#: container, so a client that failed short of that - no such container, exec
#: refused - cannot produce it however it fails. That is the whole point;
#: `docker exec` merges its own diagnostics into this same stdout pipe, so
#: nothing else arriving on it distinguishes the two (#1065).
#:
#: ``exec`` then replaces the shell, so the agent inherits the pid the timeout
#: path signals and the argv it was given. The marker is passed as an argument
#: rather than interpolated, which keeps this script a constant.
_ANNOUNCE_THEN_EXEC = 'printf "%s\\n" "$1"; shift; exec "$@"'


def _build_exec_command(
    container_name: str,
    command: list[str],
    working_directory: str | None,
    environment: dict[str, str] | None,
) -> list[str]:
    """Build the docker exec command list, wrapped so the process announces itself."""
    exec_cmd = ["docker", "exec", "-i", "-w", working_directory or "/workspace"]
    if environment:
        for key, value in environment.items():
            exec_cmd.extend(["-e", f"{key}={value}"])
    exec_cmd.append(container_name)
    exec_cmd.extend(["sh", "-c", _ANNOUNCE_THEN_EXEC, "syn-launch", AGENT_LAUNCH_MARKER, *command])
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
