"""#2107: archive size and growth for /health, read from the directory alone."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import pytest

from syn_adapters.session_inventory.archive_usage import measure_archive_usage
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

NOW = 1_800_000_000.0
DAY = 86_400.0


def _write(root: Path, name: str, size: int, age_days: float) -> None:
    path = root / name
    path.write_bytes(b"x" * size)
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))


def test_counts_objects_and_references_and_windows_growth_by_mtime(tmp_path: Path) -> None:
    _write(tmp_path, "a" * 64, 100, 0.5)
    _write(tmp_path, "b" * 64, 200, 3)
    _write(tmp_path, "c" * 64, 400, 30)
    _write(tmp_path, f".ref-{'d' * 64}", 10, 0.1)
    _write(tmp_path, ".lock-ab", 1, 0)  # on disk, but neither an object nor growth
    (tmp_path / "nested").mkdir()
    usage = measure_archive_usage(tmp_path, NOW)
    assert usage is not None
    assert (usage.object_count, usage.reference_count) == (3, 1)
    assert usage.stored_bytes == 711
    assert usage.added_bytes_24h == 110
    assert usage.added_bytes_7d == 310
    assert usage.filesystem_free_bytes > 0


def test_a_missing_archive_is_not_measured(tmp_path: Path) -> None:
    assert measure_archive_usage(tmp_path / "absent", NOW) is None


async def test_compressing_an_object_keeps_when_it_was_archived(tmp_path: Path) -> None:
    body = b"line\n" * 2000
    ref = await LocalSessionTranscriptArchive(tmp_path, compress=False).put(body)
    path = tmp_path / ref.sha256
    os.utime(path, (NOW - 30 * DAY, NOW - 30 * DAY))
    archive = LocalSessionTranscriptArchive(tmp_path)
    outcome = archive.compress_in_place(hashlib.sha256(body).hexdigest(), apply=True)
    assert outcome is not None and outcome.after < outcome.before
    assert path.stat().st_mtime == NOW - 30 * DAY
