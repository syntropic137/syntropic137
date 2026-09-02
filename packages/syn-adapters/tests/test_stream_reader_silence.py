"""A stream that stops producing complete lines must say so (issue #1061).

A hung phase spins the read loop for its entire timeout, up to an hour, emitting
nothing. These tests pin the log that makes that visible, and pin the VALUES it
reports: an earlier version returned a bool from ``line()``, so the caller
logged a constant 120 for every stall, and a test asserting only on the
substring "resumed after" passed against it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic import stream_reader
from syn_adapters.workspace_backends.agentic.stream_reader import _Silence

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

WARN = stream_reader._SILENCE_WARN_SECONDS
REPEAT = stream_reader._SILENCE_REPEAT_SECONDS


class _FakeProc:
    pid = 4242


async def _drain(gen: AsyncIterator[str]) -> list[str]:
    return [line async for line in gen]


def _patch(monkeypatch: pytest.MonkeyPatch, reads: list[bytes | None], clock: list[float]) -> None:
    """Feed read_lines a scripted read sequence and a scripted monotonic clock.

    The clock is scripted because the counter measures elapsed time, not polls.
    Returning sentinels instantly would otherwise prove only counting logic.
    """
    i = [0]

    async def fake_read(_proc: _FakeProc) -> bytes | None:
        j = i[0]
        i[0] += 1
        return reads[j] if j < len(reads) else None

    t = [0]

    def fake_monotonic() -> float:
        k = min(t[0], len(clock) - 1)
        t[0] += 1
        return clock[k]

    monkeypatch.setattr(stream_reader, "_read_next_line", fake_read)
    monkeypatch.setattr(stream_reader.time, "monotonic", fake_monotonic)


def test_elapsed_is_measured_from_the_clock_not_counted_polls() -> None:
    """The unit under the logs: one poll spanning ten seconds is ten seconds."""
    s = _Silence()
    assert s.tick(1000.0) is False, "the first silent poll only starts the clock"
    assert s.elapsed(1010.0) == 10.0
    assert s.stalled(1000.0 + WARN - 1) is False
    assert s.stalled(1000.0 + WARN) is True


def test_line_returns_the_stall_it_ended_not_a_flag() -> None:
    """The exact regression codex found: a bool here made the caller log a constant."""
    s = _Silence()
    s.tick(0.0)
    ended = s.line(WARN + 37.0)
    assert ended == WARN + 37.0, "must be the measured stall, not a constant"
    assert s.line(WARN + 40.0) is None, "a line with no preceding stall reports nothing"


def test_a_short_quiet_gap_does_not_warn() -> None:
    s = _Silence()
    s.tick(0.0)
    assert s.tick(WARN - 1.0) is False


def test_a_long_stall_repeats_on_the_interval_and_not_faster() -> None:
    """The invariant: reports are spaced by REPEAT, whatever the poll rate."""
    s = _Silence()
    s.tick(0.0)
    assert s.tick(WARN) is True, "first report at the threshold"
    assert s.tick(WARN + 1.0) is False, "not once per poll"
    assert s.tick(WARN + REPEAT - 1.0) is False
    assert s.tick(WARN + REPEAT) is True, "second report one interval later"
    assert s.tick(WARN + REPEAT + 1.0) is False


def test_the_clock_resets_so_a_second_stall_reports_again() -> None:
    """Breaks the property for the SECOND stall specifically.

    A tracker that never resets reports once per process and stays silent
    through every later stall. Only the second stall exposes it.
    """
    s = _Silence()
    s.tick(0.0)
    assert s.tick(WARN) is True
    s.line(WARN + 1.0)
    s.tick(WARN + 2.0)
    assert s.tick(WARN + 2.0 + WARN) is True, "each stall reports; state must reset"


@pytest.mark.asyncio
async def test_the_loop_reports_a_stall_with_the_measured_duration(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """End to end through read_lines, asserting the number in the message."""
    # One monotonic read per loop iteration: start the stall, then observe it
    # 500s later, then read the line that ends it.
    _patch(monkeypatch, [b"", b"", b"back\n", None], [0.0, 500.0, 500.0, 500.0])

    with caplog.at_level(logging.INFO):
        lines = await _drain(stream_reader.read_lines(_FakeProc(), None, 0.0))

    assert lines == ["back"]
    warned = [r for r in caplog.records if "No complete stdout line" in r.getMessage()]
    assert warned, "a stall past the threshold must be reported"
    assert "500s" in warned[0].getMessage(), "reports the measured stall, not a constant"
    resumed = [r for r in caplog.records if "resumed after" in r.getMessage()]
    assert resumed and "500s" in resumed[0].getMessage()


@pytest.mark.asyncio
async def test_the_warning_does_not_claim_the_process_is_hung(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A long tool call looks identical from here, so the log must not overclaim.

    A healthy agent emits tool_use and stays quiet until tool_result. Wording
    that calls this a hang would be wrong on every such phase.
    """
    _patch(monkeypatch, [b"", b"", None], [0.0, 400.0, 400.0])

    with caplog.at_level(logging.WARNING):
        await _drain(stream_reader.read_lines(_FakeProc(), None, 0.0))

    text = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "no complete stdout line" in text
    for overclaim in ("hung", "not a slow command", "wrote nothing", "alive but silent"):
        assert overclaim not in text, f"log must not assert {overclaim!r}"
