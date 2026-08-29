"""A timed-out stream must surface as a non-zero exit code (#969).

Measured on the Mac Mini: a phase with `timeout_seconds: 30` running `sleep 240`
was cut off at ~33s and reported `completed` with `error_message: None`. Three
runs across two timeout values confirmed the timeout was firing:

    timeout_seconds=15 -> phase duration 16.704689
    timeout_seconds=30 -> phase duration 33.004841 and 32.566433

The reason the truncation was invisible is that the transport swallows it:

    sleep 60                  + SIGTERM -> returncode -15   (detectable)
    docker exec ... sleep 120 + SIGTERM -> returncode 0     (INVISIBLE)

CRITICAL FOR ANYONE EDITING THESE TESTS: the fake process must exit 0 when
terminated. A test built on `sleep` passes against the bug, because `sleep`
returns -15 and the old code would have surfaced that. Using a SIGTERM-ignoring
child is what makes this test able to fail.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from syn_adapters.workspace_backends.agentic.stream_helpers import _cleanup_process
from syn_adapters.workspace_backends.agentic.stream_reader import StreamOutcome, read_lines

pytestmark = pytest.mark.unit

# Ignores SIGTERM and exits 0, reproducing `docker exec`'s behaviour.
_EXITS_ZERO_ON_SIGTERM = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
    "sys.stdout.write('line one\\n'); sys.stdout.flush()\n"
    "time.sleep(30)\n"
)


async def _spawn() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        _EXITS_ZERO_ON_SIGTERM,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def test_the_transport_really_does_hide_the_timeout() -> None:
    """Negative control. Without this, the assertions below prove nothing.

    If a future runtime made SIGTERM yield a non-zero code here, this test would
    fail and tell you the other tests had become tautologies.
    """
    proc = await _spawn()
    await asyncio.sleep(0.3)
    assert await _cleanup_process(proc) == 0, (
        "the fake process must exit 0 on SIGTERM, or these tests cannot fail"
    )


async def test_read_lines_reports_truncation() -> None:
    proc = await _spawn()
    outcome = StreamOutcome()
    start = time.monotonic()
    lines = [line async for line in read_lines(proc, 1.0, start, outcome)]
    await _cleanup_process(proc)

    assert outcome.timed_out is True
    assert lines == ["line one"], "lines before the cut must still be delivered"


async def test_a_stream_that_ends_on_its_own_is_not_marked_truncated() -> None:
    """The flag must mean 'cut off', not merely 'the loop stopped'."""
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        "print('only line')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    outcome = StreamOutcome()
    lines = [line async for line in read_lines(proc, 30.0, time.monotonic(), outcome)]
    await _cleanup_process(proc)

    assert outcome.timed_out is False
    assert lines == ["only line"]


async def test_outcome_is_optional_for_existing_callers() -> None:
    """The parameter is additive; omitting it must not break the read loop."""
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        "print('x')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    lines = [line async for line in read_lines(proc, 30.0, time.monotonic())]
    await _cleanup_process(proc)
    assert lines == ["x"]
