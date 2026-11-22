"""Bounded-memory reads of stored archive objects (#2107).

A splice reference names a small slice of a possibly large base. Reading it
must cost the slice, not the base: the whole base is still hashed, so the
slice is only trusted once the base verifies, but only the slice is kept.
"""

from __future__ import annotations

import hashlib
import zlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO

CHUNK = 1024 * 1024


class BodyWindow:
    """Hashes a body chunk by chunk, keeping only bytes ``[start, end)``."""

    def __init__(self, start: int = 0, end: int = 0) -> None:
        self._start = start
        self._end = end
        self._hash = hashlib.sha256()
        self.size = 0
        self.kept = bytearray()

    def feed(self, chunk: bytes) -> None:
        low = max(self._start - self.size, 0)
        high = min(self._end - self.size, len(chunk))
        if low < high:
            self.kept += chunk[low:high]
        self._hash.update(chunk)
        self.size += len(chunk)

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def inflate_into(source: BinaryIO, window: BodyWindow) -> bool:
    """Feed one complete gzip stream's body to ``window``; ``False`` if ``source`` is anything else.

    On ``False`` the window holds partial bytes and must be discarded.
    """
    inflater = zlib.decompressobj(wbits=31)
    try:
        while not inflater.eof:
            chunk = inflater.unconsumed_tail or source.read(CHUNK)
            if not chunk:
                window.feed(inflater.flush())
                break
            window.feed(inflater.decompress(chunk, CHUNK))
    except zlib.error:
        return False
    return inflater.eof and not inflater.unused_data and not source.read(1)


def copy_into(source: BinaryIO, window: BodyWindow) -> None:
    while chunk := source.read(CHUNK):
        window.feed(chunk)
