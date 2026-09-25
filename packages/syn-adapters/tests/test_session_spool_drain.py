"""Retry a partially drained page against the durable journal and archive."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentic_isolation.session_spool import SpoolEntry, SpoolPage

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
from syn_adapters.session_inventory.spool_drain import LocalSpoolDrain
from syn_domain.contexts.agent_sessions import CaptureLocalTranscriptHandler, RunIdentity

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg

pytestmark = pytest.mark.integration


async def test_interrupted_page_retries_without_duplicate_evidence(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
) -> None:
    run = RunIdentity(source_instance_id=str(uuid4()), execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    archive = LocalSessionTranscriptArchive(tmp_path)
    await journal.ensure_ready()
    await archive.ensure_ready()
    bodies = tuple(
        json.dumps(
            {
                "agent": "ClaudeCode",
                "source_format": "claude-code-jsonl",
                "session_id": native,
                "raw": json.dumps({"sessionId": native}) + "\r\n",
            },
            indent=2,
        ).encode()
        for native in ("first", "second")
    )
    entries = tuple(
        SpoolEntry(
            sequence=index,
            archive_sha256=hashlib.sha256(body).hexdigest(),
            byte_count=len(body),
            agent="ClaudeCode",
            native_session_id=native,
        )
        for index, (native, body) in enumerate(zip(("first", "second"), bodies, strict=True), 1)
    )
    reader = AsyncMock()
    reader.page.return_value = SpoolPage(schema_version=1, watermark=2, entries=entries)
    reader.read.side_effect = [bodies[0], OSError("container disappeared")]
    capture = CaptureLocalTranscriptHandler(archive, journal, AgenticNativeSessionEvidence())
    with pytest.raises(OSError, match="disappeared"):
        await LocalSpoolDrain(capture).page(reader, run=run, spool_id="host-spool")
    assert await journal.watermark(run) == 1
    # Recreate the drain and replay its complete page, as after worker restart.
    reader.read.side_effect = list(bodies)
    progress = await LocalSpoolDrain(capture).page(reader, run=run, spool_id="host-spool")
    assert progress.next_after is None
    assert progress.watermark == 2
    assert await journal.watermark(run) == 2
    for entry, body in zip(entries, bodies, strict=True):
        assert (tmp_path / entry.archive_sha256).read_bytes() == body

    # A replay after deletion advances the source cursor without restoring bytes
    # or altering the immutable acquisition history.
    from syn_domain.contexts.agent_sessions import ArchivedTranscript

    removed = ArchivedTranscript(sha256=entries[0].archive_sha256, size=len(bodies[0]))
    await archive.delete(removed)
    reader.read.side_effect = list(bodies)
    replay = await LocalSpoolDrain(capture).page(reader, run=run, spool_id="host-spool")
    assert replay.captured == 1 and replay.deleted == 1
    assert replay.next_after is None and replay.watermark == 2
    assert await journal.watermark(run) == 2
    assert await archive.get(removed) is None
