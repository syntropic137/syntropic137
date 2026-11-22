"""The local archive works with no remote store and verifies exact bytes."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

import pytest
from pydantic import ValidationError

from syn_adapters.session_inventory.local_archive import (
    CompressionStatus,
    LocalSessionTranscriptArchive,
)
from syn_domain.contexts.agent_sessions import ArchivedTranscript, TranscriptIntegrityError

pytestmark = pytest.mark.unit


async def test_exact_bytes_survive_restarts_and_concurrent_duplicate_capture(
    tmp_path: Path,
) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path / "archive")
    await archive.ensure_ready()
    body = b'{"native_id":"unchanged"}\r\n\x00\xff'
    refs = await asyncio.gather(*(archive.put(body) for _ in range(20)))
    assert len(set(refs)) == 1
    assert refs[0].sha256 == hashlib.sha256(body).hexdigest()
    restarted = LocalSessionTranscriptArchive(tmp_path / "archive")
    assert await restarted.get(refs[0]) == body
    assert not list((tmp_path / "archive").glob(".capture-*"))


async def test_corruption_never_becomes_a_successful_capture_receipt(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(b"original")
    (tmp_path / ref.sha256).write_bytes(b"corrupted")
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(ref)
    with pytest.raises(TranscriptIntegrityError):
        await archive.put(b"original")


async def test_absence_and_unavailable_storage_remain_distinct(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(b"original")
    (tmp_path / ref.sha256).unlink()
    assert await archive.get(ref) is None
    (tmp_path / ref.sha256).mkdir()
    with pytest.raises(IsADirectoryError):
        await archive.get(ref)


async def test_oversized_sparse_corruption_is_rejected_before_reading(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(b"original")
    with (tmp_path / ref.sha256).open("r+b") as corrupted:
        corrupted.truncate(8 * 1024 * 1024 * 1024)
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(ref)


def test_archive_reference_cannot_escape_storage_directory() -> None:
    with pytest.raises(ValidationError):
        ArchivedTranscript(sha256="../another-file", size=0)


async def test_source_identity_survives_restarts_and_cannot_be_rebound(tmp_path: Path) -> None:
    from syn_adapters.session_inventory.installation_identity import installation_identity

    identities = await asyncio.gather(
        *(asyncio.to_thread(installation_identity, tmp_path) for _ in range(10))
    )
    assert len(set(identities)) == 1
    assert installation_identity(tmp_path) == identities[0]
    with pytest.raises(ValueError, match="differs"):
        installation_identity(tmp_path, "another-installation")


def test_configured_identity_is_persisted_even_if_override_is_later_removed(tmp_path: Path) -> None:
    from syn_adapters.session_inventory.installation_identity import installation_identity

    assert installation_identity(tmp_path, "my-installation") == "my-installation"
    assert installation_identity(tmp_path) == "my-installation"


async def test_deletion_survives_restart_and_rejects_repeated_capture(tmp_path: Path) -> None:
    from syn_domain.contexts.agent_sessions import TranscriptDeletedError

    archive = LocalSessionTranscriptArchive(tmp_path)
    body = b"permanently removed transcript"
    ref = await archive.put(body)
    await archive.delete(ref)
    assert not (tmp_path / ref.sha256).exists()
    restarted = LocalSessionTranscriptArchive(tmp_path)
    assert await restarted.get(ref) is None
    with pytest.raises(TranscriptDeletedError):
        await restarted.put(body)
    await restarted.delete(ref)
    other = await restarted.put(b"unrelated transcript")
    assert await restarted.get(other) == b"unrelated transcript"


async def test_tombstone_before_unlink_crash_remains_denied(tmp_path: Path) -> None:
    from syn_domain.contexts.agent_sessions import TranscriptDeletedError

    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(b"body")
    # Simulate the durable intermediate state after marker fsync, before unlink.
    (tmp_path / f".deleted-{ref.sha256}").touch()
    assert await archive.get(ref) is None
    with pytest.raises(TranscriptDeletedError):
        await archive.put(b"body")
    await archive.delete(ref)
    assert not (tmp_path / ref.sha256).exists()


async def test_concurrent_puts_cannot_restore_deleted_body(tmp_path: Path) -> None:
    from syn_domain.contexts.agent_sessions import TranscriptDeletedError

    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(b"body")
    outcomes = await asyncio.gather(
        *(LocalSessionTranscriptArchive(tmp_path).put(b"body") for _ in range(30)),
        archive.delete(ref),
        *(LocalSessionTranscriptArchive(tmp_path).put(b"body") for _ in range(30)),
        return_exceptions=True,
    )
    assert all(
        not isinstance(item, Exception) or isinstance(item, TranscriptDeletedError)
        for item in outcomes
    )
    assert not (tmp_path / ref.sha256).exists()
    assert await archive.get(ref) is None


_ENVELOPE = b'{"scs_version":"1.0","raw":"' + b'{\\"type\\":\\"assistant\\"}\\n' * 4000 + b'"}'


async def test_objects_are_stored_compressed_and_read_back_exact(tmp_path: Path) -> None:
    """#2107: compression is physical only; key, size and reads are the raw bytes."""
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(_ENVELOPE)
    assert ref.sha256 == hashlib.sha256(_ENVELOPE).hexdigest() and ref.size == len(_ENVELOPE)
    stored = (tmp_path / ref.sha256).read_bytes()
    assert stored[:2] == b"\x1f\x8b" and len(stored) * 10 < len(_ENVELOPE)
    assert await LocalSessionTranscriptArchive(tmp_path).get(ref) == _ENVELOPE
    # A duplicate capture verifies the compressed object instead of failing.
    assert await archive.put(_ENVELOPE) == ref


async def test_uncompressed_objects_stay_readable_and_writable(tmp_path: Path) -> None:
    plain = LocalSessionTranscriptArchive(tmp_path, compress=False)
    ref = await plain.put(_ENVELOPE)
    assert (tmp_path / ref.sha256).read_bytes() == _ENVELOPE
    assert await LocalSessionTranscriptArchive(tmp_path).get(ref) == _ENVELOPE
    # An uncompressed body that happens to start with the gzip magic is itself.
    magic = b"\x1f\x8b not gzip"
    magic_ref = await plain.put(magic)
    assert await LocalSessionTranscriptArchive(tmp_path).get(magic_ref) == magic


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda b: b[:-9], id="truncated"),
        pytest.param(lambda b: b + b"\x00", id="trailing"),
        pytest.param(lambda b: b[:20] + bytes([b[20] ^ 0xFF]) + b[21:], id="flipped"),
        pytest.param(
            lambda _: gzip.compress(_ENVELOPE.replace(b"assistant", b"assistanT"), mtime=0),
            id="other-body",
        ),
        pytest.param(lambda _: gzip.compress(_ENVELOPE + b"x", mtime=0), id="longer-body"),
    ],
)
async def test_damaged_compressed_objects_never_read_as_the_body(
    tmp_path: Path, damage: Callable[[bytes], bytes]
) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(_ENVELOPE)
    target = tmp_path / ref.sha256
    target.write_bytes(damage(target.read_bytes()))
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(ref)


async def test_oversized_compressed_object_is_rejected_before_inflating(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(b"original")
    with (tmp_path / ref.sha256).open("r+b") as corrupted:
        corrupted.truncate(8 * 1024 * 1024 * 1024)
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(ref)


async def test_compress_in_place_measures_then_rewrites_without_changing_reads(
    tmp_path: Path,
) -> None:
    plain = LocalSessionTranscriptArchive(tmp_path, compress=False)
    ref = await plain.put(_ENVELOPE)
    tiny = await plain.put(b"x")
    archive = LocalSessionTranscriptArchive(tmp_path)
    assert sorted(archive.object_keys()) == sorted([ref.sha256, tiny.sha256])
    dry = archive.compress_in_place(ref.sha256, apply=False)
    assert dry is not None and dry.status is CompressionStatus.COMPRESSED
    assert dry.before == len(_ENVELOPE) and dry.after < dry.before // 10
    assert (tmp_path / ref.sha256).read_bytes() == _ENVELOPE  # dry run wrote nothing
    applied = archive.compress_in_place(ref.sha256, apply=True)
    assert applied == dry
    assert (tmp_path / ref.sha256).stat().st_size == dry.after
    assert await archive.get(ref) == _ENVELOPE
    again = archive.compress_in_place(ref.sha256, apply=True)
    assert again is not None and again.status is CompressionStatus.ALREADY_COMPRESSED
    small = archive.compress_in_place(tiny.sha256, apply=True)
    assert small is not None and small.status is CompressionStatus.INCOMPRESSIBLE
    assert (tmp_path / tiny.sha256).read_bytes() == b"x"
    assert not list(tmp_path.glob(".compress-*"))


async def test_compress_in_place_never_rewrites_a_corrupt_or_deleted_object(
    tmp_path: Path,
) -> None:
    plain = LocalSessionTranscriptArchive(tmp_path, compress=False)
    ref = await plain.put(_ENVELOPE)
    gone = await plain.put(_ENVELOPE + b" ")
    corrupt = _ENVELOPE.replace(b"assistant", b"assistanT")
    (tmp_path / ref.sha256).write_bytes(corrupt)
    archive = LocalSessionTranscriptArchive(tmp_path)
    with pytest.raises(TranscriptIntegrityError):
        archive.compress_in_place(ref.sha256, apply=True)
    assert (tmp_path / ref.sha256).read_bytes() == corrupt
    await archive.mark_deleted(gone)
    assert archive.compress_in_place(gone.sha256, apply=True) is None
    assert archive.compress_in_place("0" * 64, apply=True) is None
    with pytest.raises(ValueError, match="key"):
        archive.compress_in_place("../escape", apply=True)


@pytest.mark.parametrize("damage", ["truncated", "trailing"])
async def test_compress_in_place_verifies_a_gzip_object_before_reporting_it_done(
    tmp_path: Path, damage: str
) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(_ENVELOPE)
    stored = (tmp_path / ref.sha256).read_bytes()
    damaged = stored[:-8] if damage == "truncated" else stored + b"\0garbage"
    (tmp_path / ref.sha256).write_bytes(damaged)
    with pytest.raises(TranscriptIntegrityError):
        archive.compress_in_place(ref.sha256, apply=True)
    assert (tmp_path / ref.sha256).read_bytes() == damaged


async def test_uncompressed_body_starting_with_gzip_magic_is_still_compressed(
    tmp_path: Path,
) -> None:
    body = b"\x1f\x8b" + _ENVELOPE
    ref = await LocalSessionTranscriptArchive(tmp_path, compress=False).put(body)
    archive = LocalSessionTranscriptArchive(tmp_path)
    outcome = archive.compress_in_place(ref.sha256, apply=True)
    assert outcome is not None and outcome.status is CompressionStatus.COMPRESSED
    assert gzip.decompress((tmp_path / ref.sha256).read_bytes()) == body
    assert await archive.get(ref) == body


async def test_temporaries_of_a_killed_writer_are_reclaimed(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    ref = await archive.put(_ENVELOPE)
    other = await archive.put(_ENVELOPE + b" ")
    stale = [tmp_path / f"{prefix}{ref.sha256}-killed" for prefix in (".capture-", ".compress-")]
    unrelated = tmp_path / f".compress-{other.sha256}-killed"
    for path in [*stale, unrelated]:
        path.write_bytes(b"orphaned transcript copy")
    archive.compress_in_place(ref.sha256, apply=False)
    assert not any(path.exists() for path in stale)
    assert unrelated.exists()
    for path in stale:
        path.write_bytes(b"orphaned transcript copy")
    await archive.delete(ref)
    assert not any(path.exists() for path in stale)
    await archive.put(_ENVELOPE + b" ")
    assert not unrelated.exists()
