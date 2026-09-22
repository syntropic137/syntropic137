"""Content-addressed archive on a host-owned durable volume (#1398).

Workspace teardown must never remove this directory. Keys are server-computed
hashes, never native IDs or source paths. Publish a complete fsynced object with
an atomic hard link; concurrent captures cannot replace existing bytes.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from syn_domain.contexts.agent_sessions import ArchivedTranscript, TranscriptIntegrityError


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
        self._put(b"")

    def _put(self, body: bytes) -> ArchivedTranscript:
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
                if self._get(ref) is None:
                    raise FileNotFoundError("archive object disappeared during capture") from None
            _sync_directory(self._root)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return ref

    async def put(self, body: bytes) -> ArchivedTranscript:
        return await asyncio.to_thread(self._put, body)

    def _get(self, reference: ArchivedTranscript) -> bytes | None:
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
