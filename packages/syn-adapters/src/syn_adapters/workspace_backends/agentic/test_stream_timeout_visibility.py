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

from syn_adapters.workspace_backends.agentic.stream_adapter import (
    _TIMEOUT_EXIT_CODE,
    _resolve_stream_exit_code,
)
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


class TestResolveStreamExitCode:
    """The branch that actually fixes the bug.

    A codex review found the earlier tests proved only that `read_lines` sets
    the flag -- deleting the adapter's forcing branch left every one of them
    green. These target the decision itself.
    """

    def test_timeout_with_a_success_status_becomes_the_timeout_code(self) -> None:
        """The whole bug: docker exec says 0, but the work was cut off."""
        assert _resolve_stream_exit_code(0, timed_out=True) == _TIMEOUT_EXIT_CODE

    def test_timeout_with_no_status_becomes_the_timeout_code(self) -> None:
        assert _resolve_stream_exit_code(None, timed_out=True) == _TIMEOUT_EXIT_CODE

    def test_a_clean_stream_is_never_rewritten(self) -> None:
        assert _resolve_stream_exit_code(0, timed_out=False) == 0

    def test_a_real_failure_status_survives_a_timeout(self) -> None:
        """A specific status beats a generic 'timed out' - the operator needs it."""
        assert _resolve_stream_exit_code(137, timed_out=True) == 137

    def test_an_interrupt_status_is_left_alone(self) -> None:
        """Cancellation is routed by interrupt_requested, never by status.

        130 must reach the cancel path untouched; rewriting it to 124 would turn
        a user-requested cancel into a phase failure.
        """
        assert _resolve_stream_exit_code(130, timed_out=False) == 130
        assert _resolve_stream_exit_code(130, timed_out=True) == 130


class TestPerStreamAttribution:
    """One adapter serves concurrent executions, so results must not cross.

    `last_exit_code` is adapter-wide: between the adapter setting it and the
    handler reading it, another stream can overwrite it, and a successful phase
    would inherit this one's timeout status. Each stream therefore also gets its
    own copy on its own StreamOutcome.
    """

    def test_two_outcomes_do_not_share_state(self) -> None:
        timed_out = StreamOutcome()
        clean = StreamOutcome()

        timed_out.timed_out = True
        timed_out.exit_code = _resolve_stream_exit_code(0, timed_out=True)
        clean.exit_code = _resolve_stream_exit_code(0, timed_out=False)

        assert timed_out.exit_code == _TIMEOUT_EXIT_CODE
        assert clean.exit_code == 0, "a concurrent clean stream must keep its own status"

    def test_outcome_defaults_are_not_shared_between_instances(self) -> None:
        """A mutable default would make every stream share one record."""
        first, second = StreamOutcome(), StreamOutcome()
        first.timed_out = True
        assert second.timed_out is False
