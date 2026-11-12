"""PhaseProfileQueryService.profiles reads tokens and resources from one snapshot (#2251)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.orchestration.slices.phase_profiles.query_service import (
    PhaseProfileQueryService,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = pytest.mark.unit


class _Connection:
    """Records, per read, whether it ran inside a read-only REPEATABLE READ transaction."""

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

    async def fetch(self, _query: str, *_args: object) -> list[object]:
        self.reads_in_snapshot.append(self._in_snapshot)
        return []


class _Pool:
    def __init__(self, conn: _Connection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Connection]:
        yield self._conn


@pytest.mark.asyncio
async def test_tokens_and_resources_are_read_in_one_snapshot() -> None:
    conn = _Connection()
    service = PhaseProfileQueryService(cast("asyncpg.Pool", _Pool(conn)), CostCalculator())

    profiles = await service.profiles(
        "wf", ["exec-1"], timedelta(days=7), now=datetime(2026, 11, 12, tzinfo=UTC)
    )

    assert conn.reads_in_snapshot == [True, True]
    assert profiles.executions == 1


@pytest.mark.asyncio
async def test_no_executions_reads_nothing() -> None:
    conn = _Connection()
    service = PhaseProfileQueryService(cast("asyncpg.Pool", _Pool(conn)), CostCalculator())

    profiles = await service.profiles("wf", [], timedelta(days=7))

    assert conn.reads_in_snapshot == []
    assert profiles.executions == 0
