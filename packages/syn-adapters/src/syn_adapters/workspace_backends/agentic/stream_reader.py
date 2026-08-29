"""Line-reading helper for agentic event stream adapter.

Extracted from stream_helpers.py to reduce module cognitive complexity.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.agentic.stream_helpers import _is_stream_timed_out

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _read_next_line(
    proc: asyncio.subprocess.Process,
) -> bytes | None:
    """Read the next line from stdout, returning None on EOF or process exit.

    Returns empty bytes sentinel (b"") when a timeout occurs but the process
    is still running (caller should continue). Returns None to signal stop.
    """
    if proc.stdout is None:
        return None
    try:
        line_bytes = await asyncio.wait_for(
            proc.stdout.readline(),
            timeout=1.0,
        )
    except TimeoutError:
        if proc.returncode is not None:
            return None
        return b""  # sentinel: timeout but process alive — keep going
    return line_bytes if line_bytes else None


@dataclass
class StreamOutcome:
    """Why the read loop stopped.

    Truncation MUST be reported as data, not inferred from an exit code (#969).
    `docker exec` returns 0 when SIGTERM'd -- verified directly:

        sleep 60                  + SIGTERM -> returncode -15
        docker exec ... sleep 120 + SIGTERM -> returncode 0

    So a timed-out phase was indistinguishable from a clean finish, and reported
    `completed` while its work had been cut off mid-flight.
    """

    timed_out: bool = False


async def read_lines(
    proc: asyncio.subprocess.Process,
    stream_timeout: float | None,
    start_time: float,
    outcome: StreamOutcome | None = None,
) -> AsyncIterator[str]:
    """Read and yield decoded lines from process stdout.

    Args:
        outcome: optional caller-owned record set when the loop stops early.
            An async generator cannot return a value to an ``async for``, so the
            caller passes in the object it wants filled.
    """
    while True:
        if _is_stream_timed_out(stream_timeout, start_time):
            if outcome is not None:
                outcome.timed_out = True
            break

        raw = await _read_next_line(proc)
        if raw is None:
            break
        if raw == b"":
            continue  # timeout but process still running

        line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
        if line:
            yield line
