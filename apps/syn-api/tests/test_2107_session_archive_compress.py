"""The archive compression pass reports, resumes and never rewrites a bad object (#2107)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_api.session_archive_compress import compress_archive

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_BODY = b'{"raw":"' + b"line\\n" * 5000 + b'"}'


async def _archive(tmp_path: Path) -> LocalSessionTranscriptArchive:
    plain = LocalSessionTranscriptArchive(tmp_path, compress=False)
    for n in range(3):
        await plain.put(_BODY + str(n).encode())
    await plain.put(b"x")
    return LocalSessionTranscriptArchive(tmp_path)


async def test_dry_run_reports_savings_and_writes_nothing(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = compress_archive(archive, apply=False, budget_seconds=60)
    assert (report.objects, report.rewritten, report.incompressible) == (4, 3, 1)
    assert report.bytes_after * 10 < report.bytes_before
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert "would be rewritten:   3" in report.lines(apply=False)


async def test_apply_rewrites_then_a_rerun_finds_nothing_to_do(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    first = compress_archive(archive, apply=True, budget_seconds=60)
    assert first.rewritten == 3 and not first.integrity_failures
    second = compress_archive(archive, apply=True, budget_seconds=60)
    assert (second.rewritten, second.already_compressed, second.incompressible) == (0, 3, 1)


async def test_corrupt_objects_are_reported_and_left_alone(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    victim = next(p for p in tmp_path.iterdir() if p.stat().st_size > 100)
    victim.write_bytes(victim.read_bytes()[:-1] + b"!")
    report = compress_archive(archive, apply=True, budget_seconds=60)
    assert report.integrity_failures == [victim.name] and report.rewritten == 2
    assert victim.read_bytes().endswith(b"!")


async def test_budget_stops_the_pass(tmp_path: Path) -> None:
    archive = await _archive(tmp_path)
    ticks = iter([0.0, 0.0, 0.0, 99.0])
    report = compress_archive(archive, apply=True, budget_seconds=1, clock=lambda: next(ticks))
    assert report.stopped_by_budget and report.objects == 2
