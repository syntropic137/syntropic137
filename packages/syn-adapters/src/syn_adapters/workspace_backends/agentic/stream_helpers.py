"""Stream helper functions for AgenticEventStreamAdapter.

Extracted from stream_adapter.py to reduce module cognitive complexity.
Handles process management for docker exec streaming.
Line-reading is in stream_reader.py.
"""

from __future__ import annotations

import asyncio
import logging
import time

from syn_domain.contexts.orchestration import AGENT_LAUNCH_MARKER

logger = logging.getLogger(__name__)

#: Announce the launch from inside the container, then become the agent.
#:
#: Two separate things must be true before the marker may be printed, and the
#: script establishes both, in order.
#:
#: A process exists in the container at all. Reaching this script requires the
#: daemon to have accepted the exec, so a client that failed short of that - no
#: such container, exec refused - cannot produce the marker however it fails.
#: That is load-bearing because `docker exec` merges its own diagnostics into
#: this same stdout pipe, so nothing else arriving on it tells the two apart.
#:
#: The agent argv can become that process. ``exec`` replaces the shell only if
#: the target resolves and is executable; when it does not, the shell carries on
#: and exits 126/127 - having already printed the marker, which made a missing
#: or non-executable agent binary byte-identical to a real launch, the one
#: distinction the marker exists to draw (#1065). So the announcement is guarded
#: by the questions the kernel is about to ask: does the name resolve, is it a
#: regular file, is it executable. Both halves of the guard earn their place -
#: dash hands back any path containing a slash unchecked where bash rejects it,
#: so resolution alone would pass a non-executable file on some images and not
#: others. A failure still reaches the stream as the shell's own diagnostic;
#: only the false claim is withheld.
#:
#: This is a predicate, not a proof: an executable whose interpreter or loader
#: is missing satisfies it and fails ``exec`` anyway. That residue errs the safe
#: way - it over-reports a launch, which merely withholds the "never started"
#: claim, where under-reporting would assert it falsely. Nothing portable does
#: better. A shell cannot observe its own successful ``exec``, and the one
#: after-the-fact signal that looks like it could - an EXIT trap, which runs
#: only when ``exec`` failed - is honoured by dash and skipped by bash, so it
#: would silently do nothing depending on which /bin/sh the image ships.
#:
#: ``exec`` then replaces the shell, so the agent inherits the pid the timeout
#: path signals and the argv it was given. The marker is passed as an argument
#: rather than interpolated, which keeps this script a constant.
_ANNOUNCE_RUNNABLE_THEN_EXEC = (
    'agent=$(command -v "$2") && [ -f "$agent" ] && [ -x "$agent" ] '
    '&& printf "%s\\n" "$1"; shift; exec "$@"'
)


def _build_exec_command(
    container_name: str,
    command: list[str],
    working_directory: str | None,
    environment: dict[str, str] | None,
) -> list[str]:
    """Build the docker exec command list, wrapped so a startable agent announces itself."""
    exec_cmd = ["docker", "exec", "-i", "-w", working_directory or "/workspace"]
    if environment:
        for key, value in environment.items():
            exec_cmd.extend(["-e", f"{key}={value}"])
    exec_cmd.append(container_name)
    exec_cmd.extend(
        ["sh", "-c", _ANNOUNCE_RUNNABLE_THEN_EXEC, "syn-launch", AGENT_LAUNCH_MARKER, *command]
    )
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
