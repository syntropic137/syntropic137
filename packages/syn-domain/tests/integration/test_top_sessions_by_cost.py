"""`top_by_cost` must rank by cost across the whole history, against real SQL.

WHY THIS FILE EXISTS (#2228). The first ranking of `/costs/summary`
`top_sessions` sorted `list_all()` in Python, and `list_all()` sees only the
newest 500 summaries by TIME. An older, expensive session was simply not there
to be ranked (review of PR #2225). Which session wins is decided by the query's
ORDER BY and DISTINCT ON, which a fake connection never executes, so it is
pinned here against a real database.

Costs are near the canonical ceiling ($100,000) so sessions other tests leave in
a shared database cannot outrank the ones these tests assert on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MODEL = "claude-sonnet-4-5-20250929"
_LIST_ALL_WINDOW = 500


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


def _summary(session_id: str, cost: Decimal | None, at: datetime):
    """One session_summary row; ``cost=None`` reports no ``total_cost_usd``."""
    reported = {} if cost is None else {"total_cost_usd": float(cost)}
    return {
        "event_type": SESSION_SUMMARY,
        "session_id": session_id,
        "time": at,
        "total_input_tokens": 10,
        "total_output_tokens": 1,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "model": _MODEL,
        **reported,
    }


def _service(event_store):
    from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
        SessionCostQueryService,
    )

    return SessionCostQueryService(event_store.pool)


async def test_an_expensive_session_older_than_the_newest_500_ranks_first(event_store) -> None:
    now = datetime.now(UTC)
    expensive = f"sess-old-expensive-{uuid4()}"
    cheap = [
        _summary(f"sess-cheap-{uuid4()}", Decimal("0.01"), now - timedelta(seconds=i))
        for i in range(_LIST_ALL_WINDOW)
    ]
    await event_store.insert_batch(
        [_summary(expensive, Decimal("99999"), now - timedelta(days=1)), *cheap]
    )
    service = _service(event_store)

    # The premise of the test: the newest-500 window cannot see it.
    assert expensive not in {c.session_id for c in await service.list_all(_LIST_ALL_WINDOW)}

    top = await service.top_by_cost(1)

    assert [c.session_id for c in top] == [expensive]
    assert top[0].total_cost_usd == Decimal("99999")


async def test_ranked_by_newest_reported_cost_and_capped(event_store) -> None:
    now = datetime.now(UTC)
    first, second, third = (f"sess-rank-{n}-{uuid4()}" for n in range(3))
    re_reported = f"sess-re-reported-{uuid4()}"
    unreported = f"sess-unreported-{uuid4()}"
    await event_store.insert_batch(
        [
            # Inserted out of cost order, so insertion order is not the answer.
            _summary(third, Decimal("99997"), now - timedelta(minutes=3)),
            _summary(first, Decimal("99999"), now - timedelta(minutes=2)),
            _summary(second, Decimal("99998"), now - timedelta(minutes=1)),
            # Its older summary would rank first; the newest one is what counts.
            _summary(re_reported, Decimal("99999.5"), now - timedelta(minutes=5)),
            _summary(re_reported, Decimal("0.02"), now),
            _summary(unreported, None, now),
        ]
    )

    top = await _service(event_store).top_by_cost(2)

    assert [c.session_id for c in top] == [first, second]
