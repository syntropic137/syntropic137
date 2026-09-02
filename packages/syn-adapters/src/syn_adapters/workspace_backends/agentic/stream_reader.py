"""Line-reading helper for agentic event stream adapter.

Extracted from stream_helpers.py to reduce module cognitive complexity.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.agentic.stream_helpers import _is_stream_timed_out

logger = logging.getLogger(__name__)

#: Seconds of unbroken silence from a live process before we say so.
#: A hung phase currently spins the read loop once a second for its whole
#: timeout - up to an hour - and emits nothing. That looks identical from
#: outside to a phase between token batches, so the run is only ever ended by
#: a wall clock set for an unrelated reason (issue #1061).
#:
#: This distinguishes the two states nothing else can tell apart: the process
#: is ALIVE and writing nothing, versus the reader having stopped reading. A
#: log line here means the former, because the sentinel is only returned while
#: the process is running.
_SILENCE_WARN_SECONDS: int = 120

#: Log again on this interval so a long stall leaves a trail rather than one
#: line, and so the gap between entries measures the stall.
_SILENCE_REPEAT_SECONDS: int = 300

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


def _remaining_str(stream_timeout: float | None, start_time: float) -> str:
    """Human-readable time left on the stream deadline, for the silence log."""
    if stream_timeout is None:
        return "none set"
    # time.monotonic to match _is_stream_timed_out, which owns start_time.
    # The loop clock has a different epoch and would report nonsense here.
    remaining = stream_timeout - (time.monotonic() - start_time)
    return f"{remaining:.0f}s"


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
    silent_seconds = 0
    lines_read = 0

    while True:
        if _is_stream_timed_out(stream_timeout, start_time):
            if silent_seconds >= _SILENCE_WARN_SECONDS:
                logger.warning(
                    "Stream deadline reached after %ds of unbroken silence "
                    "(pid=%s, %d lines read). The process was alive and wrote "
                    "nothing; this is not a slow command.",
                    silent_seconds,
                    proc.pid,
                    lines_read,
                )
            if outcome is not None:
                outcome.timed_out = True
            break

        raw = await _read_next_line(proc)
        if raw is None:
            break
        if raw == b"":
            # One second elapsed with the process alive and nothing written.
            silent_seconds += 1
            if silent_seconds == _SILENCE_WARN_SECONDS or (
                silent_seconds > _SILENCE_WARN_SECONDS
                and (silent_seconds - _SILENCE_WARN_SECONDS) % _SILENCE_REPEAT_SECONDS == 0
            ):
                logger.warning(
                    "Agent process alive but silent for %ds (pid=%s); "
                    "%d lines read so far. Stream deadline in %s.",
                    silent_seconds,
                    proc.pid,
                    lines_read,
                    _remaining_str(stream_timeout, start_time),
                )
            continue  # timeout but process still running

        if silent_seconds >= _SILENCE_WARN_SECONDS:
            logger.info(
                "Agent process resumed after %ds of silence (pid=%s).",
                silent_seconds,
                proc.pid,
            )
        silent_seconds = 0
        lines_read += 1

        line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
        if line:
            yield line
