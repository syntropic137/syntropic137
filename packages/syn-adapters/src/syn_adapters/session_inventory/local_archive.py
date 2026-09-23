"""Content-addressed archive on a host-owned durable volume (#1398).

Workspace teardown must never remove this directory. Keys are server-computed
hashes, never native IDs or source paths. Publish a complete fsynced object with
an atomic hard link; concurrent captures cannot replace existing bytes.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from syn_domain.contexts.agent_sessions import (
    ArchivedTranscript,
    TranscriptDeletedError,
    TranscriptIntegrityError,
)


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalSessionTranscriptArchive:
    def __init__(self, root: Path) -> None:
        self._root = root

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
                output.write(body)
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

    def _delete(self, reference: ArchivedTranscript) -> None:
        with self._lock(reference.sha256):
            marker = self._root / f".deleted-{reference.sha256}"
            with marker.open("ab") as tombstone:
                tombstone.flush()
                os.fsync(tombstone.fileno())
            _sync_directory(self._root)
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
                if os.fstat(source.fileno()).st_size != reference.size:
                    raise TranscriptIntegrityError(
                        "archived transcript failed integrity verification"
                    )
                # Bound the read even if the object grows after fstat. One extra
                # byte distinguishes a longer object from the expected content.
                body = source.read(reference.size + 1)
        except FileNotFoundError:
            return None
        if len(body) != reference.size or hashlib.sha256(body).hexdigest() != reference.sha256:
            raise TranscriptIntegrityError("archived transcript failed integrity verification")
        return body

    async def get(self, reference: ArchivedTranscript) -> bytes | None:
        return await asyncio.to_thread(self._get, reference)

    async def is_deleted(self, reference: ArchivedTranscript) -> bool:
        return await asyncio.to_thread(self._deleted, reference.sha256)
