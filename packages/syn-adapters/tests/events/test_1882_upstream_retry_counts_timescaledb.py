"""Upstream retry counts survive the real TimescaleDB write, query and API (#1882).

The unit tests for the route hand it ready-made `UpstreamRetryCount` rows, so
they never execute `UPSTREAM_RETRY_COUNTS_SQL`. This writes through the
production writer (`AgentEventStore.record_observation`), counts with the
production query, and serves the answer through the production route: several
provider/model/kind groups, a phase that left the model unset, and rows older
than the window, which must not be counted.

Uses the shared `test_infrastructure` fixture (ADR-034): test-stack on port
15432, else testcontainers.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


async def _retry(store, *, session_id, provider, model, kind, attempt=2):
    from syn_shared.events import UPSTREAM_RETRY
    from syn_shared.upstream_failure import UpstreamRetryObservation

    await store.record_observation(
        session_id=session_id,
        observation_type=UPSTREAM_RETRY,
        data=dataclasses.asdict(
            UpstreamRetryObservation(
                provider=provider, requested_model=model, upstream_kind=kind, attempt=attempt
            )
        ),
        execution_id=f"exec-{uuid4()}",
        phase_id="verify",
    )


@pytest.mark.integration
class TestUpstreamRetryCountsRoundTrip:
    async def test_groups_nulls_and_the_window_reach_the_api(self, event_store):
        from syn_api.routes.observability import get_upstream_retries

        # Unique providers, so rows other tests wrote to the shared store
        # cannot move these counts.
        codex = f"codex-{uuid4().hex[:8]}"
        claude = f"claude-{uuid4().hex[:8]}"
        recent = f"rt-{uuid4()}"
        old = f"rt-old-{uuid4()}"

        for attempt in (2, 3):
            await _retry(
                event_store,
                session_id=recent,
                provider=codex,
                model="gpt-5.5-codex",
                kind="capacity",
                attempt=attempt,
            )
        await _retry(
            event_store, session_id=recent, provider=claude, model=None, kind="rate_limited"
        )
        await _retry(
            event_store,
            session_id=recent,
            provider=codex,
            model="gpt-5.5-codex",
            kind="rate_limited",
        )
        # Outside the 24h window: written now, then moved two days back.
        await _retry(
            event_store, session_id=old, provider=codex, model="gpt-5.5-codex", kind="capacity"
        )
        await _retry(event_store, session_id=old, provider=claude, model=None, kind="rate_limited")
        async with event_store.pool.acquire() as conn:
            moved = await conn.execute(
                "UPDATE agent_events SET time = now() - interval '2 days' WHERE session_id = $1",
                old,
            )
        assert moved == "UPDATE 2"

        with patch("syn_api._wiring.get_event_store_instance", return_value=event_store):
            response = await get_upstream_retries(window="24h")

        mine = {
            (c.provider, c.requested_model, c.upstream_kind): c.retries
            for c in response.counts
            if c.provider in (codex, claude)
        }
        assert mine == {
            (codex, "gpt-5.5-codex", "capacity"): 2,
            (codex, "gpt-5.5-codex", "rate_limited"): 1,
            (claude, None, "rate_limited"): 1,
        }
        assert response.total >= sum(mine.values())
