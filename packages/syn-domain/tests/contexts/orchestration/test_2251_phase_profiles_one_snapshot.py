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
    """Records each transaction it opens, and which one (if any) each read ran in."""

    def __init__(self) -> None:
        self.transactions: list[tuple[str, bool]] = []
        self.reads: list[int | None] = []
        self.executes: list[tuple[int | None, str]] = []
        self._open: int | None = None

    @asynccontextmanager
    async def transaction(self, *, isolation: str, readonly: bool) -> AsyncIterator[None]:
        self.transactions.append((isolation, readonly))
        self._open = len(self.transactions) - 1
        try:
            yield
        finally:
            self._open = None

    async def execute(self, query: str, *_args: object) -> str:
        self.executes.append((self._open, query))
        return "SET"

    async def fetch(self, _query: str, *_args: object) -> list[object]:
        self.reads.append(self._open)
        return []


class _Pool:
    def __init__(self, conn: _Connection) -> None:
        self._conn = conn
        self.acquisitions = 0

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Connection]:
        self.acquisitions += 1
        yield self._conn


@pytest.mark.asyncio
async def test_tokens_and_resources_are_read_in_one_snapshot() -> None:
    conn = _Connection()
    pool = _Pool(conn)
    service = PhaseProfileQueryService(cast("asyncpg.Pool", pool), CostCalculator())

    profiles = await service.profiles(
        "wf", ["exec-1"], timedelta(days=7), now=datetime(2026, 11, 12, tzinfo=UTC)
    )

    assert pool.acquisitions == 1
    assert conn.transactions == [("repeatable_read", True)]
    assert conn.reads == [0, 0]
    # agent_event_span.custom_plans: the plan setting, inside that one transaction.
    assert conn.executes == [(0, "SET LOCAL plan_cache_mode = force_custom_plan")]
    assert profiles.executions == 1


@pytest.mark.asyncio
async def test_no_executions_reads_nothing() -> None:
    conn = _Connection()
    service = PhaseProfileQueryService(cast("asyncpg.Pool", _Pool(conn)), CostCalculator())

    profiles = await service.profiles("wf", [], timedelta(days=7))

    assert conn.reads == []
    assert profiles.executions == 0
