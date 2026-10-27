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


def measure_archive_usage(root: Path, now: float) -> ArchiveUsage | None:
    """One pass over ``root``; ``None`` when it does not exist."""
    stored = objects = references = day = week = 0
    try:
        entries = os.scandir(root)
    except FileNotFoundError:
        return None
    with entries:
        for entry in entries:
            try:
                stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue  # removed mid-walk
            if not entry.is_file(follow_symlinks=False):
                continue
            stored += stat.st_size
            is_object = _OBJECT_NAME.fullmatch(entry.name) is not None
            is_reference = _REFERENCE.fullmatch(entry.name) is not None
            objects += is_object
            references += is_reference
            if not (is_object or is_reference):
                continue
            age = now - stat.st_mtime
            if age < _DAY:
                day += stat.st_size
            if age < _WEEK_DAYS * _DAY:
                week += stat.st_size
    return ArchiveUsage(
        stored_bytes=stored,
        object_count=objects,
        reference_count=references,
        added_bytes_24h=day,
        added_bytes_7d=week,
        filesystem_free_bytes=shutil.disk_usage(root).free,
    )
