"""``top_by_cost`` reads a bounded number of rows however long the history is.

#2228: ranking ``list_all()`` in Python loaded every session's token rows and
priced each one before keeping five. ``top_by_cost`` must push the LIMIT into
SQL and price only the ids that come back. A fake connection cannot execute
ORDER BY, so which session wins is pinned against real SQL in
``tests/integration/test_top_sessions_by_cost.py``; this file pins the bound.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    _TOP_BY_COST_QUERY,
    SessionCostQueryService,
)
from syn_shared.events import SESSION_SUMMARY

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

#: Far more history than any page, so an unbounded read is visible in the counts.
_HISTORY = 10_000


@dataclass
class _HistoryConnection:
    """Answers the ranking query the way Postgres would, and counts what it returns."""

    costs: dict[str, Decimal]
    queries: list[str] = field(default_factory=list)
    rows_returned: int = 0

    async def fetch(self, query: str, *args: object) -> list[dict[str, str]]:
        self.queries.append(query)
        assert query == _TOP_BY_COST_QUERY
        event_type, limit = args
        assert event_type == SESSION_SUMMARY
        assert isinstance(limit, int)
        ranked = sorted(self.costs, key=lambda sid: self.costs[sid], reverse=True)[:limit]
        self.rows_returned += len(ranked)
        return [{"session_id": sid} for sid in ranked]


@dataclass
class _Acquire:
    conn: _HistoryConnection

    async def __aenter__(self) -> _HistoryConnection:
        return self.conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


@dataclass
class _Pool:
    conn: _HistoryConnection

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def _service(
    conn: _HistoryConnection, priced: set[str] | None = None
) -> tuple[SessionCostQueryService, list[list[str]]]:
    """The real service, with ``get_many`` recording which ids it was asked to price."""
    service = SessionCostQueryService(_Pool(conn))  # type: ignore[arg-type]  # a fake pool
    asked: list[list[str]] = []

    async def get_many(session_ids: Sequence[str]) -> dict[str, SessionCost]:
        asked.append(list(session_ids))
        # Reversed: a mapping's order is not a ranking, so nothing may rely on it.
        return {
            sid: SessionCost(session_id=sid, total_cost_usd=conn.costs[sid])
            for sid in reversed(session_ids)
            if priced is None or sid in priced
        }

    service.get_many = get_many  # type: ignore[method-assign]
    return service, asked


def _history() -> dict[str, Decimal]:
    # The most expensive session is FIRST, i.e. the oldest: a newest-N window
    # would never reach it.
    costs = {f"sess-{i:05d}": Decimal(i) / 100 for i in range(1, _HISTORY)}
    return {"sess-oldest-expensive": Decimal("500"), **costs}


async def test_the_limit_is_pushed_to_sql_and_only_those_ids_are_priced() -> None:
    conn = _HistoryConnection(_history())
    service, asked = _service(conn)

    top = await service.top_by_cost(5)

    assert conn.queries == [_TOP_BY_COST_QUERY]
    assert "LIMIT $2" in _TOP_BY_COST_QUERY
    assert conn.rows_returned == 5
    assert asked == [
        ["sess-oldest-expensive", "sess-09999", "sess-09998", "sess-09997", "sess-09996"]
    ]
    assert [c.total_cost_usd for c in top] == [
        Decimal("500"),
        Decimal("99.99"),
        Decimal("99.98"),
        Decimal("99.97"),
        Decimal("99.96"),
    ]


async def test_the_sql_rank_survives_pricing_and_a_vanished_session_is_dropped() -> None:
    conn = _HistoryConnection(
        {"sess-a": Decimal("3"), "sess-b": Decimal("2"), "sess-c": Decimal("1")}
    )
    # get_many omits a session with no cost data.
    service, _ = _service(conn, priced={"sess-c", "sess-a"})

    top = await service.top_by_cost(3)

    assert [c.session_id for c in top] == ["sess-a", "sess-c"]
