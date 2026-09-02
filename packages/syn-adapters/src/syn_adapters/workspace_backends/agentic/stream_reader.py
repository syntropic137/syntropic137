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


@dataclass
class _Silence:
    """Tracks how long a live process has written nothing.

    Kept out of ``read_lines`` so that loop stays about reading lines. The
    counter is in seconds because ``_read_next_line`` yields its sentinel on a
    one-second poll.
    """

    seconds: int = 0
    lines_read: int = 0

    def tick(self) -> bool:
        """Record one silent second. True when this second should be reported."""
        self.seconds += 1
        if self.seconds == _SILENCE_WARN_SECONDS:
            return True
        past = self.seconds - _SILENCE_WARN_SECONDS
        return past > 0 and past % _SILENCE_REPEAT_SECONDS == 0

    def line(self) -> bool:
        """Record a real line. True when this ends a stall worth reporting."""
        was_stalled = self.stalled
        self.seconds = 0
        self.lines_read += 1
        return was_stalled

    @property
    def stalled(self) -> bool:
        return self.seconds >= _SILENCE_WARN_SECONDS


def _log_still_silent(
    proc: asyncio.subprocess.Process,
    silence: _Silence,
    stream_timeout: float | None,
    start_time: float,
) -> None:
    logger.warning(
        "Agent process alive but silent for %ds (pid=%s); %d lines read so far. "
        "Stream deadline in %s.",
        silence.seconds,
        proc.pid,
        silence.lines_read,
        _remaining_str(stream_timeout, start_time),
    )


def _log_deadline_reached(proc: asyncio.subprocess.Process, silence: _Silence) -> None:
    if not silence.stalled:
        return
    logger.warning(
        "Stream deadline reached after %ds of unbroken silence (pid=%s, %d lines "
        "read). The process was alive and wrote nothing; this is not a slow command.",
        silence.seconds,
        proc.pid,
        silence.lines_read,
    )


def _deadline_passed(
    proc: asyncio.subprocess.Process,
    silence: _Silence,
    stream_timeout: float | None,
    start_time: float,
    outcome: StreamOutcome | None,
) -> bool:
    """True when the stream deadline has passed, recording why on the way out."""
    if not _is_stream_timed_out(stream_timeout, start_time):
        return False
    _log_deadline_reached(proc, silence)
    if outcome is not None:
        outcome.timed_out = True
    return True


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
    silence = _Silence()

    while True:
        if _deadline_passed(proc, silence, stream_timeout, start_time, outcome):
            break

        raw = await _read_next_line(proc)
        if raw is None:
            break
        if raw == b"":
            # One second elapsed with the process alive and nothing written.
            if silence.tick():
                _log_still_silent(proc, silence, stream_timeout, start_time)
            continue  # timeout but process still running

        if silence.line():
            logger.info(
                "Agent process resumed after %ds of silence (pid=%s).",
                _SILENCE_WARN_SECONDS,
                proc.pid,
            )

        line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
        if line:
            yield line
