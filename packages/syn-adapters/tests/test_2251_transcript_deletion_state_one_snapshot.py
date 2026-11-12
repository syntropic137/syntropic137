"""A transcript's deletion state is read from ONE snapshot (#2251).

``state()`` reads the tombstone (local status), then the delivery jobs and
deletion checkpoints (replica status). At READ COMMITTED each statement takes
its own snapshot, so one response could pair a local status from one moment
with a replica status from another.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest

from syn_adapters.session_inventory.capture_deletion_worker import PROPAGATED_REASONS
from syn_adapters.session_inventory.deletion_fence import DeletionFence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.transcript_deletions import PostgresTranscriptDeletions
from syn_domain.contexts.agent_sessions import CataloguedCapture

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from asyncpg import Pool

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

SOURCE = "install-1"
DESTINATION = "replica-1"


class _Connection:
    """Answers the tombstone read, then the replica read; records each read's snapshot."""

    def __init__(self) -> None:
        self.reads_in_snapshot: list[bool] = []
        self._in_snapshot = False

    @asynccontextmanager
    async def transaction(self, *, isolation: str, readonly: bool) -> AsyncIterator[None]:
        self._in_snapshot = isolation == "repeatable_read" and readonly
        try:
            yield
        finally:
            self._in_snapshot = False

    async def fetch(self, query: str, *_args: object) -> list[object]:
        self.reads_in_snapshot.append(self._in_snapshot)
        if "count(*)" in query:
            return [{"state": "queued", "n": "1"}]
        return [
            {
                "reason": PROPAGATED_REASONS[0],
                "content_hash": None,
                "requested_at": "2026-11-12T00:00:00Z",
                "deleted_at": None,
            }
        ]


class _Pool:
    def __init__(self, conn: _Connection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Connection]:
        yield self._conn


async def test_local_and_replica_status_come_from_one_snapshot(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = CataloguedCapture.model_validate(
        {
            "run": {"source_instance_id": SOURCE, "execution_id": "exec-1"},
            "producer_id": "test",
            "capture_id": "cap-1",
            "harness": "codex",
            "native_id": "native",
            "content_format": "envelope",
            "archive": (await archive.put(b"body")).model_dump(),
        }
    )
    conn = _Connection()
    pool = cast("Pool", _Pool(conn))
    deletions = PostgresTranscriptDeletions(
        pool, SOURCE, DESTINATION, archive=archive, fence=DeletionFence(pool, SOURCE)
    )

    state = await deletions.state(capture)

    assert conn.reads_in_snapshot == [True, True]
    assert state is not None
    assert state.local_status == "pending"
    assert [r.status for r in state.replicas] == ["queued"]
