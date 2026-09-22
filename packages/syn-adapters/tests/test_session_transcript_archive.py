"""The local archive works with no remote store and verifies exact bytes."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from pydantic import ValidationError

from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
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
