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
#: WHAT THE SENTINEL ACTUALLY PROVES, and it is less than it first appears:
#: no COMPLETE stdout line arrived during the poll, and process exit had not
#: been observed at the last check. It does NOT prove the process wrote no
#: bytes - readline() holds partial bytes until a newline - and it does not
#: distinguish a hang from a long tool call, because a healthy agent emits
#: tool_use and then stays quiet until its tool_result. The log wording below
#: is limited to what is actually established.
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

    lines_read: int = 0
    started_at: float | None = None
    last_reported: float = 0.0

    def tick(self, now: float) -> bool:
        """Note a poll that yielded nothing. True when this should be reported.

        Elapsed time is measured from a monotonic clock rather than by counting
        polls: a poll is at LEAST a second, and scheduler delay makes a count a
        lower bound rather than a duration.
        """
        if self.started_at is None:
            self.started_at = now
            return False
        elapsed = now - self.started_at
        if elapsed < _SILENCE_WARN_SECONDS:
            return False
        if self.last_reported == 0.0 or elapsed - self.last_reported >= _SILENCE_REPEAT_SECONDS:
            self.last_reported = elapsed
            return True
        return False

    def line(self, now: float) -> float | None:
        """Note a real line. Returns the stall it ended, or None if there was none.

        Returns the duration rather than a bool so the caller can log the value
        it actually measured. Returning a bool here made the caller log a
        constant, and a test asserting only on a substring did not catch it.
        """
        ended = self.elapsed(now) if self.stalled(now) else None
        self.started_at = None
        self.last_reported = 0.0
        self.lines_read += 1
        return ended

    def elapsed(self, now: float) -> float:
        return 0.0 if self.started_at is None else now - self.started_at

    def stalled(self, now: float) -> bool:
        return self.elapsed(now) >= _SILENCE_WARN_SECONDS


def _log_still_silent(
    proc: asyncio.subprocess.Process,
    silence: _Silence,
    stream_timeout: float | None,
    start_time: float,
    now: float,
) -> None:
    logger.warning(
        "No complete stdout line from the agent for %.0fs (pid=%s); process exit "
        "not observed at the last poll; %d lines read so far. Deadline in %s.",
        silence.elapsed(now),
        proc.pid,
        silence.lines_read,
        _remaining_str(stream_timeout, start_time),
    )


def _log_deadline_reached(proc: asyncio.subprocess.Process, silence: _Silence, now: float) -> None:
    """Report a deadline reached mid-silence, in terms of what is established.

    Deliberately does NOT claim the process was hung. A long tool call looks
    identical from here: the agent emits tool_use and stays quiet until
    tool_result. What is known is that no complete line arrived for this long.
    """
    if not silence.stalled(now):
        return
    logger.warning(
        "Deadline reached with no complete stdout line for the last %.0fs "
        "(pid=%s, %d lines read in total).",
        silence.elapsed(now),
        proc.pid,
        silence.lines_read,
    )


def _deadline_passed(
    proc: asyncio.subprocess.Process,
    silence: _Silence,
    stream_timeout: float | None,
    start_time: float,
    outcome: StreamOutcome | None,
    now: float,
) -> bool:
    """True when the stream deadline has passed, recording why on the way out."""
    if not _is_stream_timed_out(stream_timeout, start_time):
        return False
    _log_deadline_reached(proc, silence, now)
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
        now = time.monotonic()
        if _deadline_passed(proc, silence, stream_timeout, start_time, outcome, now):
            break

        raw = await _read_next_line(proc)
        if raw is None:
            break
        if raw == b"":
            # One second elapsed with the process alive and nothing written.
            if silence.tick(now):
                _log_still_silent(proc, silence, stream_timeout, start_time, now)
            continue  # timeout but process still running

        ended = silence.line(now)
        if ended is not None:
            logger.info(
                "Agent stdout resumed after %.0fs without a complete line (pid=%s).",
                ended,
                proc.pid,
            )

        line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
        if line:
            yield line
