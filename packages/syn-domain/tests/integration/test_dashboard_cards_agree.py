"""The metric card and the activity heatmap must quote the same numbers.

They answered the same question from different lanes - the card from Lane 1
``SessionCompleted`` domain events, the heatmap from Lane 2 observations -
and disagreed by 851,513 tokens and $0.32 on live data. Reading one
canonical definition makes them agree by construction, so this test fails
the moment a second source of truth reappears.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MODEL = "haiku"
_VENDOR_COST_USD = 0.09439815


_MIDDAY = time(12, 0, tzinfo=UTC)


@pytest.fixture
def utc_day() -> date:
    """The one UTC date this test seeds on and queries for.

    Observations are stored in UTC while ``date.today()`` is LOCAL, and the
    heatmap buckets by the UTC day, so the test must ask the UTC question.

    Read ONCE per test (#1001). Seeding stamped ``now()`` while the window was
    built from two further clock reads, so a run crossing UTC midnight seeded
    sessions on one day and asked the heatmap about another: the heatmap
    totalled zero, the card totalled 15,550, and the two cards "disagreed" for
    a reason that has nothing to do with either query.
    """
    return datetime.now(UTC).date()


async def _record_observation_on(
    store,
    day: date,
    session_id: str,
    execution_id: str,
    observation_type: str,
    data: Mapping[str, int | float | str | None],
    *,
    seconds_past_midday: int = 0,
) -> None:
    """Write one observation at midday on ``day``, through the production writer.

    ``record_observation`` stamps ``datetime.now()`` and offers no way to say
    otherwise, so it is the wall-clock read that decides which day a session
    starts on. ``insert_one`` is that same write path one layer down - it is
    what ``record_observation`` calls, with the same validation and the same
    INSERT - and it takes the timestamp from the caller.

    These timestamps are in the FUTURE whenever the suite runs before midday,
    and that is fine: nothing under test rejects ``time > now()``. Only date
    membership and relative order matter to either query.
    """
    await store.insert_one(
        event={
            "event_type": observation_type,
            "session_id": session_id,
            "timestamp": datetime.combine(day, _MIDDAY) + timedelta(seconds=seconds_past_midday),
            **data,
        },
        execution_id=execution_id,
    )


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


async def _seed_mixed_reality(store, day: date, execution_id: str) -> None:
    """The three shapes that made the two cards disagree, all at once, on ``day``."""
    # 1. A finished claude session: placeholder turn rows, authoritative summary.
    finished = str(uuid4())
    await _record_observation_on(
        store,
        day,
        finished,
        execution_id,
        TOKEN_USAGE,
        {
            "input_tokens": 18,
            "output_tokens": 5,
            "cache_creation_tokens": 15_809,
            "cache_read_tokens": 58_179,
            "model": _MODEL,
        },
        seconds_past_midday=0,
    )
    await _record_observation_on(
        store,
        day,
        finished,
        execution_id,
        SESSION_SUMMARY,
        {
            "total_input_tokens": 18,
            "total_output_tokens": 13_300,
            "cache_creation_tokens": 15_809,
            "cache_read_tokens": 58_179,
            "total_cost_usd": _VENDOR_COST_USD,
            "model": _MODEL,
        },
        seconds_past_midday=1,
    )

    # 2. A session still running: no summary yet, must still be counted.
    running = str(uuid4())
    await _record_observation_on(
        store,
        day,
        running,
        execution_id,
        TOKEN_USAGE,
        {
            "input_tokens": 500,
            "output_tokens": 250,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 1_000,
            "model": _MODEL,
        },
        seconds_past_midday=2,
    )

    # 3. A codex session: reports no cost of its own, must still be priced.
    codex = str(uuid4())
    await _record_observation_on(
        store,
        day,
        codex,
        execution_id,
        SESSION_SUMMARY,
        {
            "total_input_tokens": 1_000,
            "total_output_tokens": 2_000,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 5_000,
            "total_cost_usd": None,
            "model": "claude-opus-4-20250514",
        },
        seconds_past_midday=3,
    )


class TestBothCardsReadOneSource:
    async def test_metric_card_totals_equal_heatmap_totals(self, event_store, utc_day):
        from syn_domain.contexts.agent_sessions import CostCalculator
        from syn_domain.contexts.agent_sessions.slices.canonical_totals import (
            CanonicalUsageQueryService,
        )
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        execution_id = str(uuid4())
        await _seed_mixed_reality(event_store, utc_day, execution_id)

        card = await CanonicalUsageQueryService(event_store.pool, CostCalculator()).totals(
            execution_ids={execution_id}
        )

        heatmap_buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )
        heat = {
            "tokens": sum(b.breakdown["tokens"] for b in heatmap_buckets),
            "output": sum(b.breakdown["output_tokens"] for b in heatmap_buckets),
            "cost": sum(b.breakdown["cost_usd"] for b in heatmap_buckets),
            "sessions": sum(b.breakdown["sessions"] for b in heatmap_buckets),
        }

        assert card.total_tokens == heat["tokens"]
        assert card.output_tokens == heat["output"]
        assert card.sessions == heat["sessions"]
        assert float(card.cost_usd) == pytest.approx(heat["cost"], abs=1e-3)

    async def test_totals_use_authoritative_output_not_the_placeholder(self, event_store, utc_day):
        """Sanity-anchor the agreement to the RIGHT number, not merely a shared one.

        Two cards agreeing on 5 output tokens would satisfy the test above.
        """
        from syn_domain.contexts.agent_sessions import CostCalculator
        from syn_domain.contexts.agent_sessions.slices.canonical_totals import (
            CanonicalUsageQueryService,
        )

        execution_id = str(uuid4())
        await _seed_mixed_reality(event_store, utc_day, execution_id)
        card = await CanonicalUsageQueryService(event_store.pool, CostCalculator()).totals(
            execution_ids={execution_id}
        )

        # 13,300 (finished) + 250 (running) + 2,000 (codex)
        assert card.output_tokens == 15_550
        assert card.sessions == 3
