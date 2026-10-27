"""The archive dedupe pass groups revisions, reports, resumes and loses no body (#2107)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_api.session_archive_dedupe import dedupe_archive
from syn_domain.contexts.agent_sessions import ArchivedTranscript

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _envelope(session: str, lines: int) -> bytes:
    raw = "".join(
        f'{{"n":{n},"h":"{hashlib.sha256(str(n).encode()).hexdigest()}"}}\n' for n in range(lines)
    )
    head = {"agent": "ClaudeCode", "session_id": session, "message_count": lines}
    return json.dumps({**head, "raw": raw}, separators=(",", ":")).encode()


_BODIES = [
    *(_envelope("s-1", n) for n in (30, 60, 90)),
    *(_envelope("s-2", n) for n in (30, 60)),
    _envelope("s-3", 30),
    b"not an envelope",
]


async def _archive(tmp_path: Path) -> LocalSessionTranscriptArchive:
    archive = LocalSessionTranscriptArchive(tmp_path)
    for body in _BODIES:
        await archive.put(body)
    return archive


async def _all_readable(archive: LocalSessionTranscriptArchive) -> None:
    for body in _BODIES:
        reference = ArchivedTranscript(sha256=hashlib.sha256(body).hexdigest(), size=len(body))
        assert await archive.get(reference) == body


async def test_dry_run_reports_savings_and_writes_nothing(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if not p.name.startswith(".lock-")}
    report = dedupe_archive(archive, apply=False, budget_seconds=60)
    assert (report.objects, report.not_envelopes, report.sessions, report.candidates) == (
        7,
        1,
        2,
        3,
    )
    assert report.spliced == 3 and report.bytes_after * 2 < report.bytes_before
    assert {
        p.name: p.read_bytes() for p in tmp_path.iterdir() if not p.name.startswith(".lock-")
    } == before
    assert "would be spliced:     3" in report.lines(apply=False)


async def test_apply_splices_then_a_rerun_finds_nothing_to_do(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    first = dedupe_archive(archive, apply=True, budget_seconds=60)
    assert first.spliced == 3 and not first.integrity_failures
    assert len(list(archive.object_keys())) == 4
    await _all_readable(archive)
    second = dedupe_archive(archive, apply=True, budget_seconds=60)
    assert (second.candidates, second.spliced) == (0, 0)


async def test_a_new_newest_revision_retargets_on_the_next_run(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    dedupe_archive(archive, apply=True, budget_seconds=60)
    newest = _envelope("s-1", 120)
    await archive.put(newest)
    report = dedupe_archive(archive, apply=True, budget_seconds=60)
    assert (report.spliced, report.retargeted) == (1, 2)
    await _all_readable(archive)
    assert (
        await archive.get(
            ArchivedTranscript(sha256=hashlib.sha256(newest).hexdigest(), size=len(newest))
        )
        == newest
    )


async def test_non_prefix_revisions_are_counted_and_kept(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    diverged = _envelope("s-3", 20).replace(b'\\"n\\":0,', b'\\"n\\":9,')
    assert diverged != _envelope("s-3", 20)
    await archive.put(diverged)
    report = dedupe_archive(archive, apply=True, budget_seconds=60)
    assert report.not_a_prefix == 1
    assert hashlib.sha256(diverged).hexdigest() in set(archive.object_keys())


async def test_budget_stops_the_pass(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    ticks = iter([0.0, 0.0, 99.0])
    report = dedupe_archive(archive, apply=True, budget_seconds=1, clock=lambda: next(ticks))
    assert report.stopped_by_budget and report.spliced == 1
    await _all_readable(archive)
