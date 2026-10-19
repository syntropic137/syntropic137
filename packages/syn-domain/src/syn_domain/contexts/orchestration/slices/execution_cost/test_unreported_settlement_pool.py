"""Settling an unreported summary never holds two pool connections (#1420).

The execution list and batch readers settle a null-cost summary through the
session reader, which acquires a connection of its own. Done while still
holding the first, a pool saturated by such requests deadlocks: each holds
one connection and waits for a second that none will release.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from syn_domain.agent_event_span import EventSpan
from syn_domain.contexts.agent_sessions import zero_usage_group_by
from syn_domain.contexts.agent_sessions.slices.session_cost import timescale_query as session_sql
from syn_domain.contexts.agent_sessions.slices.session_cost.test_unreported_cost import (
    _SID,
    _TURNS,
    _sql_single,
    _summary_row,
    _turn_rows,
)
from syn_domain.contexts.orchestration.slices.execution_cost import query_service as execution_sql
from syn_domain.contexts.orchestration.slices.execution_cost import (
    timescale_query as execution_single_sql,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.execution_cost.test_unreported_summary_parity import (
    _EID,
    _execution_row,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
        ExecutionCost,
    )

_CAPACITY = 20
_SPAN = EventSpan(lower=datetime(2026, 1, 1, tzinfo=UTC), upper=datetime(2027, 1, 1, tzinfo=UTC))


class _Conn:
    """Answers each query the readers send with the rows the store would hold."""

    async def fetch(self, query: str, *_args: object) -> list[dict[str, object]]:
        if query in (
            execution_sql._LIST_ALL_FROM_SUMMARY_QUERY,
            execution_sql._BY_IDS_FROM_SUMMARY_QUERY,
        ):
            return [_execution_row(_SID, None)]
        if query == execution_sql._COST_BY_PHASE_QUERY:
            return [_execution_row(_SID, None)]
        if query == session_sql._SESSION_SUMMARY_BATCH_QUERY:
            return [_summary_row(None)]
        if query == session_sql._TOKEN_USAGE_FALLBACK_BATCH_QUERY:
            return _turn_rows(_TURNS)  # type: ignore[return-value]
        return []


class _BoundedPool:
    """A fixed number of connections; no holder proceeds until all are held."""

    def __init__(self, capacity: int) -> None:
        self._slots = asyncio.Semaphore(capacity)
        self._capacity = capacity
        self._held = 0
        self._saturated = asyncio.Event()
        self._holders: set[asyncio.Task[object] | None] = set()
        self.nested = 0

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Conn]:
        task = asyncio.current_task()
        if task in self._holders:
            self.nested += 1
        async with self._slots:
            self._holders.add(task)
            self._held += 1
            if self._held == self._capacity:
                self._saturated.set()
            try:
                await self._saturated.wait()
                yield _Conn()
            finally:
                self._held -= 1
                self._holders.discard(task)


@asynccontextmanager
async def _no_custom_plans(_conn: object) -> AsyncIterator[None]:
    yield


async def _list_all(service: ExecutionCostQueryService) -> list[ExecutionCost]:
    return await service.list_all()


async def _read_for_ids(service: ExecutionCostQueryService) -> list[ExecutionCost]:
    return (await service.read_for_ids([_EID])).costs


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("read", [_list_all, _read_for_ids], ids=["list_all", "read_for_ids"])
async def test_a_saturated_pool_still_settles_every_request(
    read: Callable[[ExecutionCostQueryService], Awaitable[list[ExecutionCost]]],
) -> None:
    pool = _BoundedPool(_CAPACITY)
    expected = _sql_single(_TURNS, None).total_cost_usd
    with (
        patch("syn_domain.agent_event_span.custom_plans", _no_custom_plans),
        patch("syn_domain.agent_event_span.for_executions", AsyncMock(return_value=_SPAN)),
        patch("syn_domain.agent_event_span.for_sessions", AsyncMock(return_value=_SPAN)),
        patch("syn_domain.tool_call_counts.by_execution", AsyncMock(return_value={})),
        patch("syn_domain.tool_call_counts.by_session", AsyncMock(return_value={})),
    ):
        answers = await asyncio.wait_for(
            asyncio.gather(
                *[read(ExecutionCostQueryService(pool)) for _ in range(_CAPACITY)]  # type: ignore[arg-type]
            ),
            timeout=5,
        )

    assert pool.nested == 0
    for costs in answers:
        assert [c.total_cost_usd for c in costs] == [expected]
        assert costs[0].cost_by_phase == {"phase-1": expected}
    assert expected != Decimal("0")


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [
        execution_single_sql._TOKEN_USAGE_FALLBACK_QUERY,
        execution_sql._LIST_ALL_FROM_TOKEN_USAGE_QUERY,
        execution_sql._BY_IDS_FROM_TOKEN_USAGE_QUERY,
    ],
    ids=["single", "list", "batch"],
)
def test_execution_turn_queries_group_empty_turns_apart(query: str) -> None:
    """Execution replay prices each turn alone too, so an empty one stays a priced zero."""
    assert zero_usage_group_by() in query.split("GROUP BY", 1)[1]
