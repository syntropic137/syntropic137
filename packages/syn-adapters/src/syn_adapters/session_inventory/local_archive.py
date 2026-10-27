"""Content-addressed archive on a host-owned durable volume (#1398).

Workspace teardown must never remove this directory. Keys are server-computed
hashes, never native IDs or source paths. Publish a complete fsynced object with
an atomic hard link; concurrent captures cannot replace existing bytes.

Objects are stored gzip-compressed (#2107). Compression is a physical encoding
only: the key, ``ArchivedTranscript.size`` and every read are the exact
uncompressed bytes, verified by hash. Objects written before compression stay
readable; ``compress_in_place`` re-encodes one without changing what it reads as.

An object may instead be a splice reference (``archive_splice``): an older
revision stored as head + a slice of a newer full object (its base) + tail.
``splice_onto`` creates one only after verifying it, every read re-verifies
it, a base is pinned while referenced (deleting it first turns its referrers
back into full objects) and a base is never itself a reference, so there are no
chains. Splicing is operator-run (``just session-archive-dedupe``), never live.
"""

from __future__ import annotations

import asyncio
import fcntl
import gzip
import hashlib
import io
import os
import re
import sys
import tempfile
import zlib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO

from syn_domain.contexts.agent_sessions import (
    ArchivedTranscript,
    TranscriptDeletedError,
    TranscriptIntegrityError,
)

from .archive_splice import (
    MAX_REFERENCE_BYTES,
    SpliceReference,
    assemble,
    envelope_identity,
    plan_splice,
    reconstruct,
)
from .archive_stream import CHUNK, BodyWindow, copy_into, inflate_into

_GZIP_MAGIC = b"\x1f\x8b"
_GZIP_FRAMING = 18
"""Header plus trailer: no gzip stream is shorter."""
_OBJECT_NAME = re.compile(r"[0-9a-f]{64}")
# Temporaries are named after their digest so a writer killed before its
# cleanup ran leaves bytes the next locked operation on that digest reclaims.
_REFERENCE = ".ref-"
_TEMPORARY_PREFIXES = (".capture-", ".compress-", f".reference-{_REFERENCE}")
_PIN = ".pin-"
# Enough to hold any envelope head; identity is read from it alone.
_IDENTITY_PREFIX = 64 * 1024


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
            chunk = inflater.unconsumed_tail or source.read(CHUNK)
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


def _gzip_digest(stored: bytes) -> str | None:
    """sha256 of one complete gzip stream, inflated in bounded chunks; ``None`` if damaged."""
    window = BodyWindow()
    return window.hexdigest() if inflate_into(io.BytesIO(stored), window) else None


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class SpliceStatus(StrEnum):
    SPLICED = "spliced"
    """Stored as a reference, or with ``apply=False`` would be."""
    ALREADY_REFERENCED = "already_referenced"
    NO_SAVING = "no_saving"
    """The reference would not be smaller than the stored object, or exceeds MAX_REFERENCE_BYTES: it stays full."""
    NOT_A_PREFIX = "not_a_prefix"
    """It, or a revision referencing it, does not fit the base: it stays a full object."""
    INELIGIBLE = "ineligible"
    """Absent or deleted, or the base is absent, deleted or itself a reference."""


@dataclass(frozen=True)
class SpliceOutcome:
    status: SpliceStatus
    before: int = 0
    """Physical bytes of the full object, 0 when there is none."""
    after: int = 0
    """Bytes of the reference that replaces it, when SPLICED."""
    retargeted: int = 0
    """References to it moved onto the new base first."""


@dataclass(frozen=True)
class EnvelopeSummary:
    agent: str
    session_id: str
    size: int
    """Uncompressed size, from the gzip trailer when compressed: a hint, never verified."""


def _head_and_size(source: BinaryIO) -> tuple[bytes, int] | None:
    head = source.read(_IDENTITY_PREFIX)
    size = os.fstat(source.fileno()).st_size
    # Shorter than gzip framing: an uncompressed body that starts with the magic.
    if head[: len(_GZIP_MAGIC)] != _GZIP_MAGIC or size < _GZIP_FRAMING:
        return head, size
    source.seek(-4, os.SEEK_END)
    size = int.from_bytes(source.read(4), "little")
    try:
        return zlib.decompressobj(wbits=31).decompress(head, _IDENTITY_PREFIX), size
    except zlib.error:
        return None


@dataclass(frozen=True)
class CompressionOutcome:
    status: CompressionStatus
    before: int
    """Physical bytes before."""
    after: int
    """Physical bytes after; equal to ``before`` unless the status is COMPRESSED."""


def _publishable(reference: SpliceReference) -> bool:
    return len(reference.model_dump_json()) <= MAX_REFERENCE_BYTES


def _keep_archived_time(temporary: str, *sources: Path) -> None:
    """Give ``temporary`` the mtime of the first source that exists.

    Growth in /health is read from mtimes (#2107), so a rewrite of a revision
    already archived, as an object or as a reference, must not look new.
    """
    for source in sources:
        try:
            kept = source.stat()
        except FileNotFoundError:
            continue
        os.utime(temporary, ns=(kept.st_atime_ns, kept.st_mtime_ns))
        return


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
    def _flock(self, name: str) -> Iterator[None]:
        with (self._root / name).open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @contextmanager
    def _lock(self, *digests: str) -> Iterator[None]:
        # Fixed stripes bound lock-file growth. Locks cover publication, reads,
        # and tombstone-before-unlink, including independent worker processes.
        # Several stripes are taken once each in sorted order: flock is per open
        # file, so a stripe taken twice deadlocks, and any other order can.
        with ExitStack() as stack:
            for stripe in sorted({digest[:2] for digest in digests}):
                stack.enter_context(self._flock(f".lock-{stripe}"))
            yield

    @contextmanager
    def _splice_lock(self) -> Iterator[None]:
        """Serialises every change to references and pins; taken before any stripe."""
        with self._flock(".lock-splice"):
            yield

    def _deleted(self, digest: str) -> bool:
        return (self._root / f".deleted-{digest}").exists()

    def _put(self, body: bytes) -> ArchivedTranscript:
        digest = hashlib.sha256(body).hexdigest()
        with self._lock(digest):
            if self._deleted(digest):
                raise TranscriptDeletedError("transcript body was permanently deleted")
            return self._put_locked(body)

    def _reclaim_temporaries_locked(self, digest: str) -> None:
        """Remove a killed writer's temporaries; every writer of ``digest`` holds its lock."""
        for prefix in _TEMPORARY_PREFIXES:
            for stale in self._root.glob(f"{prefix}{digest}-*"):
                stale.unlink(missing_ok=True)

    def _put_locked(self, body: bytes) -> ArchivedTranscript:
        ref = ArchivedTranscript(sha256=hashlib.sha256(body).hexdigest(), size=len(body))
        target = self._root / ref.sha256
        self._reclaim_temporaries_locked(ref.sha256)
        descriptor, temporary = tempfile.mkstemp(prefix=f".capture-{ref.sha256}-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(_encode(body) if self._compress else body)
                output.flush()
                os.fsync(output.fileno())
            # Materializing a referrer, or re-putting a spliced body.
            _keep_archived_time(temporary, self._root / f"{_REFERENCE}{ref.sha256}")
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

    def _touch(self, name: str) -> None:
        with (self._root / name).open("ab") as marker:
            marker.flush()
            os.fsync(marker.fileno())
        _sync_directory(self._root)

    def _mark_locked(self, reference: ArchivedTranscript) -> None:
        self._touch(f".deleted-{reference.sha256}")

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
        digest = reference.sha256
        with self._splice_lock():
            referrers = self._referrers(digest)
            base = self._reference_base(digest)
            with self._lock(digest, *referrers, *([base] if base else [])):
                self._mark_locked(reference)
                # Revisions stored as slices of this body become full objects first.
                for referrer in referrers:
                    self._materialize_locked(referrer, digest)
                # A crash before unlink still denies reads and subsequent puts.
                (self._root / digest).unlink(missing_ok=True)
                self._drop_reference_locked(digest, base)
                self._reclaim_temporaries_locked(digest)
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
            spliced = self._spliced_locked(reference.sha256, reference.size)
            if spliced is None:
                return None
            body = spliced
        if len(body) != reference.size or hashlib.sha256(body).hexdigest() != reference.sha256:
            raise TranscriptIntegrityError("archived transcript failed integrity verification")
        return body

    async def get(self, reference: ArchivedTranscript) -> bytes | None:
        return await asyncio.to_thread(self._get, reference)

    async def is_deleted(self, reference: ArchivedTranscript) -> bool:
        return await asyncio.to_thread(self._deleted, reference.sha256)

    def _is_splice_base(self, digest: str) -> bool:
        with self._splice_lock():
            return any(not self._deleted(referrer) for referrer in self._referrers(digest))

    async def is_splice_base(self, reference: ArchivedTranscript) -> bool:
        """Whether live older revisions are stored as slices of these bytes.

        Deleting a base turns every referrer back into a full object, so a
        confirmed expiry of a base would grow the archive instead (#2107 R1).
        """
        return await asyncio.to_thread(self._is_splice_base, reference.sha256)

    def object_keys(self) -> Iterator[str]:
        """Every stored object's key; markers, locks and temporaries are not objects."""
        for entry in os.scandir(self._root):
            if _OBJECT_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                yield entry.name

    def _replace_locked(
        self, target: Path, encoded: bytes, prefix: str = ".compress-", *archived: Path
    ) -> None:
        """Atomically rewrite ``target``, keeping its mtime, else the first of ``archived``'s."""
        descriptor, temporary = tempfile.mkstemp(prefix=f"{prefix}{target.name}-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            _keep_archived_time(temporary, target, *archived)
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
            self._reclaim_temporaries_locked(digest)
            if self._deleted(digest):
                return None
            try:
                stored = target.read_bytes()
            except FileNotFoundError:
                return None
            outcome = _measure(digest, stored)
            if apply and outcome.encoded is not None:
                self._replace_locked(target, outcome.encoded)
            return outcome.result

    def envelope_summary(self, digest: str) -> EnvelopeSummary | None:
        """Which session a full object is a revision of, from its first bytes only."""
        with self._lock(digest):
            if self._deleted(digest):
                return None
            try:
                with (self._root / digest).open("rb") as source:
                    read = _head_and_size(source)
            except FileNotFoundError:
                return None
        identity = None if read is None else envelope_identity(read[0])
        if read is None or identity is None:
            return None
        return EnvelopeSummary(agent=identity[0], session_id=identity[1], size=read[1])

    # Splice references. Every change below runs under the splice lock and then
    # the stripes of every digest it touches, so pins cannot change underneath.

    def _reference(self, digest: str) -> SpliceReference | None:
        try:
            with (self._root / f"{_REFERENCE}{digest}").open("rb") as source:
                # read(n) allocates n up front, so bound it by the file, then the limit.
                found = os.fstat(source.fileno()).st_size
                stored = source.read(min(found, MAX_REFERENCE_BYTES) + 1)
        except FileNotFoundError:
            return None
        if len(stored) > MAX_REFERENCE_BYTES:
            raise TranscriptIntegrityError("archived transcript reference is unreadable")
        try:
            reference = SpliceReference.model_validate_json(stored)
        except ValidationError:
            raise TranscriptIntegrityError("archived transcript reference is unreadable") from None
        if reference.sha256 != digest:
            raise TranscriptIntegrityError("archived transcript reference names another body")
        return reference

    def _reference_base(self, digest: str) -> str | None:
        """The base a reference names, tolerating a damaged one: deletion must not stop."""
        try:
            reference = self._reference(digest)
        except TranscriptIntegrityError:
            return None
        return None if reference is None else reference.base_sha256

    def _referrers(self, base: str) -> list[str]:
        prefix = f"{_PIN}{base}-"
        return sorted(
            entry.name[len(prefix) :]
            for entry in os.scandir(self._root)
            if entry.name.startswith(prefix) and _OBJECT_NAME.fullmatch(entry.name[len(prefix) :])
        )

    def _window_locked(self, digest: str, start: int = 0, end: int = 0) -> BodyWindow | None:
        """Bytes ``[start, end)`` of a full object's verified body, in bounded memory.

        ``None`` when there is no full object. The whole body is hashed, so the
        kept bytes are trusted only because everything else verified too.
        """
        try:
            source = (self._root / digest).open("rb")
        except FileNotFoundError:
            return None
        with source:
            if source.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC:
                source.seek(0)
                window = BodyWindow(start, end)
                if inflate_into(source, window) and window.hexdigest() == digest:
                    return window
            # Uncompressed, including a body that happens to start with the magic.
            source.seek(0)
            window = BodyWindow(start, end)
            copy_into(source, window)
        if window.hexdigest() != digest:
            raise TranscriptIntegrityError("archived transcript failed integrity verification")
        return window

    def _full_locked(self, digest: str) -> bytes | None:
        """A full object's verified body; ``None`` when there is no full object."""
        window = self._window_locked(digest, 0, sys.maxsize)
        return None if window is None else bytes(window.kept)

    def _spliced_locked(self, digest: str, size: int | None = None) -> bytes | None:
        """The verified body a reference names; ``None`` when there is no reference.

        Only ``digest``'s stripe is held, not the base's. That is enough: the
        base's pin on ``digest`` exists before the reference does, so nothing
        removes the base without first taking this stripe, and a base's bytes
        never change (a re-encode is an atomic replace with the same body).
        """
        reference = self._reference(digest)
        if reference is None:
            return None
        if size is not None and reference.size != size:
            # Before the base is read: the caller's receipt bounds what is kept.
            raise TranscriptIntegrityError("archived transcript reference failed verification")
        end = reference.offset + reference.length
        base = self._window_locked(reference.base_sha256, reference.offset, end)
        body = None if base is None else assemble(reference, base.size, bytes(base.kept))
        if body is None:
            raise TranscriptIntegrityError("archived transcript reference failed verification")
        return body

    def _load_locked(self, digest: str) -> bytes | None:
        body = self._full_locked(digest)
        return self._spliced_locked(digest) if body is None else body

    def _drop_reference_locked(self, digest: str, base: str | None) -> None:
        (self._root / f"{_REFERENCE}{digest}").unlink(missing_ok=True)
        if base is not None:
            (self._root / f"{_PIN}{base}-{digest}").unlink(missing_ok=True)

    def _materialize_locked(self, digest: str, base: str) -> None:
        """Store a referrer of ``base`` as a full object again, then drop its reference."""
        if not self._deleted(digest) and self._window_locked(digest) is None:
            body = self._spliced_locked(digest)
            if body is not None:
                self._put_locked(body)
        self._drop_reference_locked(digest, base)

    def _commit_reference_locked(self, reference: SpliceReference, previous: str | None) -> None:
        """Pin the base, publish atomically, re-verify from disk, then release the old pin."""
        self._touch(f"{_PIN}{reference.base_sha256}-{reference.sha256}")
        target = self._root / f"{_REFERENCE}{reference.sha256}"
        self._replace_locked(
            target,
            reference.model_dump_json().encode(),
            ".reference-",
            self._root / reference.sha256,
        )
        if self._spliced_locked(reference.sha256) is None:
            raise TranscriptIntegrityError("archived transcript reference was not published")
        if previous is not None and previous != reference.base_sha256:
            (self._root / f"{_PIN}{previous}-{reference.sha256}").unlink(missing_ok=True)

    def _plan_retargets(self, referrers: list[str], base: bytes) -> list[SpliceReference] | None:
        """Verified references moving every live referrer onto ``base``; ``None`` if one cannot."""
        moves: list[SpliceReference] = []
        for referrer in referrers:
            body = None if self._deleted(referrer) else self._spliced_locked(referrer)
            if body is None:
                continue  # a deleted referrer, or a pin left by a crash before its reference
            move = plan_splice(body, base)
            if move is None or not _publishable(move) or reconstruct(move, base) != body:
                return None
            moves.append(move)
        return moves

    def splice_onto(self, digest: str, base: str, *, apply: bool) -> SpliceOutcome:
        """Store ``digest`` as a verified slice of the full object ``base``.

        Commit order: verify, pin, publish the reference, re-verify it from
        disk, and only then unlink the full object. References to ``digest``
        move onto ``base`` first, the same way, so no reference ever points at a
        reference. Re-running is idempotent. Without ``apply`` it only measures.
        """
        for key in (digest, base):
            if not _OBJECT_NAME.fullmatch(key):
                raise ValueError("not an archive object key")
        if digest == base:
            raise ValueError("an object cannot be spliced onto itself")
        with self._splice_lock():
            referrers = self._referrers(digest)
            with self._lock(digest, base, *referrers):
                return self._splice_locked(digest, base, referrers, apply=apply)

    def _stored_size(self, digest: str) -> int:
        try:
            return (self._root / digest).stat().st_size
        except FileNotFoundError:
            return 0

    def _splice_locked(
        self, digest: str, base: str, referrers: list[str], *, apply: bool
    ) -> SpliceOutcome:
        before = self._stored_size(digest)
        existing = self._reference(digest)
        settled = self._settled_locked(digest, base, existing, before)
        if settled is not None:
            return SpliceOutcome(settled)
        planned = self._plan_locked(digest, base, referrers)
        if isinstance(planned, SpliceStatus):
            return SpliceOutcome(planned, before)
        plan, moves = planned
        after = len(plan.model_dump_json())
        if after > MAX_REFERENCE_BYTES or (before and after >= before):
            return SpliceOutcome(SpliceStatus.NO_SAVING, before)
        if apply:
            previous = None if existing is None else existing.base_sha256
            self._apply_splice_locked(plan, moves, referrers, previous)
        return SpliceOutcome(SpliceStatus.SPLICED, before, after, len(moves))

    def _settled_locked(
        self, digest: str, base: str, existing: SpliceReference | None, before: int
    ) -> SpliceStatus | None:
        """Why there is nothing to do, before reading any body."""
        if self._deleted(digest) or self._deleted(base) or self._reference(base) is not None:
            return SpliceStatus.INELIGIBLE
        if existing is not None and existing.base_sha256 == base and before == 0:
            return SpliceStatus.ALREADY_REFERENCED
        return None

    def _plan_locked(
        self, digest: str, base: str, referrers: list[str]
    ) -> tuple[SpliceReference, list[SpliceReference]] | SpliceStatus:
        """Verified references for ``digest`` and every referrer, or why there are none."""
        base_body = self._full_locked(base)
        body = self._load_locked(digest)
        if base_body is None or body is None:
            return SpliceStatus.INELIGIBLE
        plan = plan_splice(body, base_body)
        moves = self._plan_retargets(referrers, base_body)
        if plan is None or moves is None:
            return SpliceStatus.NOT_A_PREFIX
        if reconstruct(plan, base_body) != body:
            raise TranscriptIntegrityError("splice reference failed verification")
        return plan, moves

    def _apply_splice_locked(
        self,
        plan: SpliceReference,
        moves: list[SpliceReference],
        referrers: list[str],
        previous: str | None,
    ) -> None:
        digest = plan.sha256
        for move in moves:
            self._commit_reference_locked(move, digest)
        for referrer in referrers:  # pins a crash left without a reference
            (self._root / f"{_PIN}{digest}-{referrer}").unlink(missing_ok=True)
        self._commit_reference_locked(plan, previous)
        (self._root / digest).unlink(missing_ok=True)
        _sync_directory(self._root)


@dataclass(frozen=True)
class _Measured:
    result: CompressionOutcome
    encoded: bytes | None
    """The verified replacement, when the object should be rewritten."""


def _measure(digest: str, stored: bytes) -> _Measured:
    """Classify by content, never by magic alone.

    A stored object whose own hash is its key is an uncompressed body, even one
    that starts with the gzip magic. Otherwise it must be one complete gzip
    stream inflating to that key; anything else is an integrity failure.
    """
    before = len(stored)
    if hashlib.sha256(stored).hexdigest() != digest:
        if stored[: len(_GZIP_MAGIC)] != _GZIP_MAGIC or _gzip_digest(stored) != digest:
            raise TranscriptIntegrityError("archived transcript failed integrity verification")
        return _Measured(
            CompressionOutcome(CompressionStatus.ALREADY_COMPRESSED, before, before), None
        )
    encoded = _encode(stored)
    if _gzip_digest(encoded) != digest:
        raise TranscriptIntegrityError("re-encoded transcript failed verification")
    if len(encoded) >= before:
        return _Measured(CompressionOutcome(CompressionStatus.INCOMPRESSIBLE, before, before), None)
    return _Measured(
        CompressionOutcome(CompressionStatus.COMPRESSED, before, len(encoded)), encoded
    )
