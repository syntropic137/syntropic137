"""How much disk the session archive uses and how fast it grows (#2107).

Growth is read from file modification times, so it needs no history and
survives restarts: an object's mtime is when it was first archived, because
``compress_in_place`` keeps it across the re-encode. "Added" bytes are the
current physical size of objects and splice references written in the
window; an object since deleted no longer counts, so this is what the window
still occupies, not a log of every write.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_OBJECT_NAME = re.compile(r"[0-9a-f]{64}")
_REFERENCE = re.compile(r"\.ref-[0-9a-f]{64}")
_DAY = 86_400.0
_WEEK_DAYS = 7


@dataclass(frozen=True)
class ArchiveUsage:
    stored_bytes: int
    """Physical bytes of every regular file in the archive directory."""
    object_count: int
    """Full objects, compressed or not."""
    reference_count: int
    """Older revisions stored as splice references."""
    added_bytes_24h: int
    added_bytes_7d: int
    filesystem_free_bytes: int


def _files(root: Path) -> Iterator[tuple[str, os.stat_result]]:
    """Every regular file directly in ``root``; one removed mid-walk is skipped."""
    with os.scandir(root) as entries:
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False):
                    yield entry.name, entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue


def measure_archive_usage(root: Path, now: float) -> ArchiveUsage | None:
    """One pass over ``root``; ``None`` when it does not exist."""
    if not root.is_dir():
        return None
    stored = objects = references = day = week = 0
    for name, stat in _files(root):
        stored += stat.st_size
        is_object = _OBJECT_NAME.fullmatch(name) is not None
        is_reference = _REFERENCE.fullmatch(name) is not None
        objects += is_object
        references += is_reference
        age = now - stat.st_mtime
        if (is_object or is_reference) and age < _WEEK_DAYS * _DAY:
            week += stat.st_size
            day += stat.st_size if age < _DAY else 0
    return ArchiveUsage(
        stored_bytes=stored,
        object_count=objects,
        reference_count=references,
        added_bytes_24h=day,
        added_bytes_7d=week,
        filesystem_free_bytes=shutil.disk_usage(root).free,
    )
