"""The metric card and the activity heatmap must quote the same numbers.

They answered the same question from different lanes - the card from Lane 1
``SessionCompleted`` domain events, the heatmap from Lane 2 observations -
and disagreed by 851,513 tokens and $0.32 on live data. Reading one
canonical definition makes them agree by construction, so this test fails
the moment a second source of truth reappears.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MODEL = "haiku"
_VENDOR_COST_USD = 0.09439815


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


async def _seed_mixed_reality(store, execution_id: str) -> None:
    """The three shapes that made the two cards disagree, all at once."""
    # 1. A finished claude session: placeholder turn rows, authoritative summary.
    finished = str(uuid4())
    await store.record_observation(
        session_id=finished,
        observation_type=TOKEN_USAGE,
        data={
            "input_tokens": 18,
            "output_tokens": 5,
            "cache_creation_tokens": 15_809,
            "cache_read_tokens": 58_179,
            "model": _MODEL,
        },
        execution_id=execution_id,
    )
    await store.record_observation(
        session_id=finished,
        observation_type=SESSION_SUMMARY,
        data={
            "total_input_tokens": 18,
            "total_output_tokens": 13_300,
            "cache_creation_tokens": 15_809,
            "cache_read_tokens": 58_179,
            "total_cost_usd": _VENDOR_COST_USD,
            "model": _MODEL,
        },
        execution_id=execution_id,
    )

    # 2. A session still running: no summary yet, must still be counted.
    running = str(uuid4())
    await store.record_observation(
        session_id=running,
        observation_type=TOKEN_USAGE,
        data={
            "input_tokens": 500,
            "output_tokens": 250,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 1_000,
            "model": _MODEL,
        },
        execution_id=execution_id,
    )

    # 3. A codex session: reports no cost of its own, must still be priced.
    codex = str(uuid4())
    await store.record_observation(
        session_id=codex,
        observation_type=SESSION_SUMMARY,
        data={
            "total_input_tokens": 1_000,
            "total_output_tokens": 2_000,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 5_000,
            "total_cost_usd": None,
            "model": "claude-opus-4-20250514",
        },
        execution_id=execution_id,
    )


class TestBothCardsReadOneSource:
    async def test_metric_card_totals_equal_heatmap_totals(self, event_store):
        from syn_domain.contexts.agent_sessions.slices.canonical_totals import (
            CanonicalUsageQueryService,
        )
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        execution_id = str(uuid4())
        await _seed_mixed_reality(event_store, execution_id)

        card = await CanonicalUsageQueryService(event_store.pool).totals(
            execution_ids={execution_id}
        )

        heatmap_buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=date.today(), end=date.today(), execution_ids={execution_id}
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

    async def test_totals_use_authoritative_output_not_the_placeholder(self, event_store):
        """Sanity-anchor the agreement to the RIGHT number, not merely a shared one.

        Two cards agreeing on 5 output tokens would satisfy the test above.
        """
        from syn_domain.contexts.agent_sessions.slices.canonical_totals import (
            CanonicalUsageQueryService,
        )

        execution_id = str(uuid4())
        await _seed_mixed_reality(event_store, execution_id)
        card = await CanonicalUsageQueryService(event_store.pool).totals(
            execution_ids={execution_id}
        )

        # 13,300 (finished) + 250 (running) + 2,000 (codex)
        assert card.output_tokens == 15_550
        assert card.sessions == 3
