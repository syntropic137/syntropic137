"""A live-but-silent agent process must say so, not vanish (issue #1061).

A hung phase spins the read loop once a second for its entire timeout, up to an
hour, emitting nothing. From outside that is indistinguishable from a phase
between token batches, so the run is only ever ended by a wall clock set for an
unrelated reason. These tests pin the log that separates the two states.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from syn_adapters.workspace_backends.agentic import stream_reader

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit


class _FakeProc:
    """Stands in for asyncio.subprocess.Process; only pid is read."""

    pid = 4242


async def _drain(gen: AsyncIterator[str]) -> list[str]:
    return [line async for line in gen]


def _patch_reads(
    monkeypatch: pytest.MonkeyPatch, reads: list[bytes | None]
) -> list[int]:
    """Feed read_lines a scripted sequence, one entry per loop iteration."""
    calls = [0]

    async def fake_read_next_line(_proc: Any) -> bytes | None:
        i = calls[0]
        calls[0] += 1
        return reads[i] if i < len(reads) else None

    monkeypatch.setattr(stream_reader, "_read_next_line", fake_read_next_line)
    return calls


@pytest.mark.asyncio
async def test_silence_below_the_threshold_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A short quiet gap is ordinary and must not warn."""
    quiet = stream_reader._SILENCE_WARN_SECONDS - 1
    _patch_reads(monkeypatch, [b""] * quiet + [b"line one\n", None])

    with caplog.at_level(logging.WARNING):
        lines = await _drain(stream_reader.read_lines(_FakeProc(), None, 0.0))

    assert lines == ["line one"]
    assert not [r for r in caplog.records if "silent" in r.getMessage()]


@pytest.mark.asyncio
async def test_silence_at_the_threshold_warns_once_and_names_the_process(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Crossing the threshold must produce exactly one warning, not one per second."""
    over = stream_reader._SILENCE_WARN_SECONDS + 5
    _patch_reads(monkeypatch, [b""] * over + [None])

    with caplog.at_level(logging.WARNING):
        await _drain(stream_reader.read_lines(_FakeProc(), None, 0.0))

    warnings = [r for r in caplog.records if "alive but silent" in r.getMessage()]
    assert len(warnings) == 1, "one warning at the threshold, not one per silent second"
    assert "4242" in warnings[0].getMessage(), "must name the process"


@pytest.mark.asyncio
async def test_a_resumed_stream_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Recovery must be visible, or a warning with no sequel reads as a hang."""
    over = stream_reader._SILENCE_WARN_SECONDS + 1
    _patch_reads(monkeypatch, [b""] * over + [b"back\n", None])

    with caplog.at_level(logging.INFO):
        lines = await _drain(stream_reader.read_lines(_FakeProc(), None, 0.0))

    assert lines == ["back"]
    assert [r for r in caplog.records if "resumed after" in r.getMessage()]


@pytest.mark.asyncio
async def test_the_counter_resets_so_a_second_stall_warns_again(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The invariant: every stall past the threshold warns, not only the first.

    A counter that never resets would warn once per process and stay quiet
    through every later stall. Breaking the reset must fail this test, and it
    is the second stall that catches it - which the earlier cases cannot.
    """
    quiet = stream_reader._SILENCE_WARN_SECONDS + 1
    _patch_reads(
        monkeypatch,
        [b""] * quiet + [b"first\n"] + [b""] * quiet + [b"second\n", None],
    )

    with caplog.at_level(logging.WARNING):
        lines = await _drain(stream_reader.read_lines(_FakeProc(), None, 0.0))

    assert lines == ["first", "second"]
    warnings = [r for r in caplog.records if "alive but silent" in r.getMessage()]
    assert len(warnings) == 2, "each stall warns; the counter must reset on a real line"
