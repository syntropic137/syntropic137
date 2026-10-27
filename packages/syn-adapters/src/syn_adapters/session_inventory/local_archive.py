"""Content-addressed archive on a host-owned durable volume (#1398).

Workspace teardown must never remove this directory. Keys are server-computed
hashes, never native IDs or source paths. Publish a complete fsynced object with
an atomic hard link; concurrent captures cannot replace existing bytes.

Objects are stored gzip-compressed (#2107). Compression is a physical encoding
only: the key, ``ArchivedTranscript.size`` and every read are the exact
uncompressed bytes, verified by hash. Objects written before compression stay
readable; ``compress_in_place`` re-encodes one without changing what it reads as.
"""

from __future__ import annotations

import asyncio
import fcntl
import gzip
import hashlib
import os
import re
import tempfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO

from syn_domain.contexts.agent_sessions import (
    ArchivedTranscript,
    TranscriptDeletedError,
    TranscriptIntegrityError,
)

_GZIP_MAGIC = b"\x1f\x8b"
_OBJECT_NAME = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


def _encode(body: bytes) -> bytes:
    # mtime=0 keeps the encoding a pure function of the body.
    return gzip.compress(body, compresslevel=6, mtime=0)


def _max_encoded_size(size: int) -> int:
    """Deflate's worst case is stored blocks: 5 bytes per 64KiB, plus framing."""
    return size + 5 * (size // 16383 + 1) + 64


def _decode(source: BinaryIO, size: int) -> bytes:
    """Inflate at most ``size + 1`` bytes; a damaged stream is an integrity failure."""
    inflater = zlib.decompressobj(wbits=31)
    out = bytearray()
    try:
        while not inflater.eof and len(out) <= size:
            chunk = inflater.unconsumed_tail or source.read(_CHUNK)
            if not chunk:
                break
            out += inflater.decompress(chunk, size + 1 - len(out))
    except zlib.error:
        raise TranscriptIntegrityError(
            "archived transcript failed integrity verification"
        ) from None
    if not inflater.eof or inflater.unused_data or source.read(1):
        raise TranscriptIntegrityError("archived transcript failed integrity verification")
    return bytes(out)


class CompressionStatus(StrEnum):
    ALREADY_COMPRESSED = "already_compressed"
    COMPRESSED = "compressed"
    """Rewritten, or with ``apply=False`` would be; ``after`` is the encoded size."""
    INCOMPRESSIBLE = "incompressible"
    """gzip would not be smaller, so the object is left uncompressed."""


def _read_object(source: BinaryIO, reference: ArchivedTranscript) -> bytes:
    """The stored bytes, inflated if compressed; the caller verifies the hash."""
    stored = os.fstat(source.fileno()).st_size
    compressed = source.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    source.seek(0)
    if stored != reference.size and not (
        compressed and stored <= _max_encoded_size(reference.size)
    ):
        raise TranscriptIntegrityError("archived transcript failed integrity verification")
    if compressed and stored != reference.size:
        return _decode(source, reference.size)
    # Bound the read even if the object grows after fstat. One extra byte
    # distinguishes a longer object from the expected content.
    body = source.read(reference.size + 1)
    if compressed and hashlib.sha256(body).hexdigest() != reference.sha256:
        # A gzip object exactly as long as its body; an uncompressed body that
        # happens to start with the gzip magic was read as itself above.
        source.seek(0)
        return _decode(source, reference.size)
    return body


def _physical(target: Path) -> tuple[int, bool] | None:
    """Stored size and whether the object is gzip; ``None`` when absent."""
    try:
        with target.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            return size, source.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class CompressionOutcome:
    status: CompressionStatus
    before: int
    """Physical bytes before."""
    after: int
    """Physical bytes after; equal to ``before`` unless the status is COMPRESSED."""


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalSessionTranscriptArchive:
    def __init__(self, root: Path, *, compress: bool = True) -> None:
        self._root = root
        self._compress = compress

    async def ensure_ready(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Test actual durable writes, not os.access(), which can lie under ACLs.
        descriptor, temporary = tempfile.mkstemp(prefix=".probe-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(b"archive durability probe")
                output.flush()
                os.fsync(output.fileno())
            _sync_directory(self._root)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @contextmanager
    def _lock(self, digest: str) -> Iterator[None]:
        # Fixed stripes bound lock-file growth. Locks cover publication, reads,
        # and tombstone-before-unlink, including independent worker processes.
        with (self._root / f".lock-{digest[:2]}").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _deleted(self, digest: str) -> bool:
        return (self._root / f".deleted-{digest}").exists()

    def _put(self, body: bytes) -> ArchivedTranscript:
        digest = hashlib.sha256(body).hexdigest()
        with self._lock(digest):
            if self._deleted(digest):
                raise TranscriptDeletedError("transcript body was permanently deleted")
            return self._put_locked(body)

    def _put_locked(self, body: bytes) -> ArchivedTranscript:
        ref = ArchivedTranscript(sha256=hashlib.sha256(body).hexdigest(), size=len(body))
        target = self._root / ref.sha256
        descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(_encode(body) if self._compress else body)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                # A collision must not acknowledge a corrupted existing object.
                if self._get_locked(ref) is None:
                    raise FileNotFoundError("archive object disappeared during capture") from None
            _sync_directory(self._root)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return ref

    async def put(self, body: bytes) -> ArchivedTranscript:
        return await asyncio.to_thread(self._put, body)

    def _mark_locked(self, reference: ArchivedTranscript) -> None:
        marker = self._root / f".deleted-{reference.sha256}"
        with marker.open("ab") as tombstone:
            tombstone.flush()
            os.fsync(tombstone.fileno())
        _sync_directory(self._root)

    def _mark(self, reference: ArchivedTranscript) -> None:
        with self._lock(reference.sha256):
            self._mark_locked(reference)

    async def mark_deleted(self, reference: ArchivedTranscript) -> None:
        """Durable anti-resurrection marker without erasing yet.

        From here every read returns absent and every put of these bytes fails,
        whatever path it comes from. Erasure follows asynchronously.
        """
        await asyncio.to_thread(self._mark, reference)

    def _delete(self, reference: ArchivedTranscript) -> None:
        with self._lock(reference.sha256):
            self._mark_locked(reference)
            # A crash before unlink still denies reads and subsequent puts.
            (self._root / reference.sha256).unlink(missing_ok=True)
            _sync_directory(self._root)

    async def delete(self, reference: ArchivedTranscript) -> None:
        """Permanently erase an exact body, retaining its anti-resurrection marker."""
        await asyncio.to_thread(self._delete, reference)

    def _get(self, reference: ArchivedTranscript) -> bytes | None:
        with self._lock(reference.sha256):
            if self._deleted(reference.sha256):
                return None
            return self._get_locked(reference)

    def _get_locked(self, reference: ArchivedTranscript) -> bytes | None:
        try:
            with (self._root / reference.sha256).open("rb") as source:
                body = _read_object(source, reference)
        except FileNotFoundError:
            return None
        if len(body) != reference.size or hashlib.sha256(body).hexdigest() != reference.sha256:
            raise TranscriptIntegrityError("archived transcript failed integrity verification")
        return body

    async def get(self, reference: ArchivedTranscript) -> bytes | None:
        return await asyncio.to_thread(self._get, reference)

    async def is_deleted(self, reference: ArchivedTranscript) -> bool:
        return await asyncio.to_thread(self._deleted, reference.sha256)

    def object_keys(self) -> Iterator[str]:
        """Every stored object's key; markers, locks and temporaries are not objects."""
        for entry in os.scandir(self._root):
            if _OBJECT_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                yield entry.name

    def _replace_locked(self, target: Path, encoded: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".compress-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            Path(temporary).replace(target)
            _sync_directory(self._root)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def compress_in_place(self, digest: str, *, apply: bool) -> CompressionOutcome | None:
        """Re-encode one stored object; ``None`` when it is absent or deleted.

        Two-layer verify before the atomic replace: the current object reads
        back as the body its key names, and the new encoding decodes to that
        same body. A crash leaves the old object or the new one, never neither.
        Without ``apply`` it only measures."""
        if not _OBJECT_NAME.fullmatch(digest):
            raise ValueError("not an archive object key")
        target = self._root / digest
        with self._lock(digest):
            physical = None if self._deleted(digest) else _physical(target)
            if physical is None:
                return None
            before, compressed = physical
            if compressed:
                return CompressionOutcome(CompressionStatus.ALREADY_COMPRESSED, before, before)
            body = self._get_locked(ArchivedTranscript(sha256=digest, size=before))
            if body is None:
                return None
            encoded = _encode(body)
            if hashlib.sha256(gzip.decompress(encoded)).hexdigest() != digest:
                raise TranscriptIntegrityError("re-encoded transcript failed verification")
            if len(encoded) >= before:
                return CompressionOutcome(CompressionStatus.INCOMPRESSIBLE, before, before)
            if apply:
                self._replace_locked(target, encoded)
            return CompressionOutcome(CompressionStatus.COMPRESSED, before, len(encoded))
