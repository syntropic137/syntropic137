"""`DISTINCT ON` must return the NEWEST session_summary, against real SQL.

WHY THIS FILE EXISTS. The unit suite for `calculate_many` uses a fake connection
that dispatches canned rows by matching the SQL text as a dictionary key. It
never parses or executes SQL, so it cannot see what the query ORDERS BY. The
cross-model review of #1115 proved that concretely: changing the shipped query
from `time DESC` to `time ASC` - selecting the OLDEST summary - left all five
unit tests green.

`DISTINCT ON (session_id) ... ORDER BY session_id, time DESC` is what preserves
the per-session `ORDER BY time DESC LIMIT 1` semantics the single-session query
had. That is a property of the SQL, so it is pinned here against a real
database, with two rows that force a choice.

A single-summary happy path would confirm nothing. The assertion has to make the
query CHOOSE.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MODEL = "claude-sonnet-4-5-20250929"

#: Deliberately far apart and both non-zero, so an off-by-one row selection is
#: visible in the assertion rather than hidden by a shared value.
_OLD_INPUT_TOKENS = 111
_NEW_INPUT_TOKENS = 999_999


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


async def _record_summary(store, session_id: str, input_tokens: int) -> None:
    await store.record_observation(
        session_id=session_id,
        observation_type=SESSION_SUMMARY,
        data={
            "total_input_tokens": input_tokens,
            "total_output_tokens": 1,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "model": _MODEL,
        },
    )


async def test_the_newest_summary_wins_when_a_session_has_two(event_store) -> None:
    """Two summaries, one session: the later `time` must be the one priced.

    Re-apply the `time DESC` -> `time ASC` mutation and this test must fail. If
    it does not, it has stopped testing the thing it was written for.
    """
    from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
        TimescaleSessionCostQuery,
    )

    session_id = f"sess-{uuid4()}"
    await _record_summary(event_store, session_id, _OLD_INPUT_TOKENS)
    await _record_summary(event_store, session_id, _NEW_INPUT_TOKENS)

    query = TimescaleSessionCostQuery(event_store.pool)
    results = await query.calculate_many([session_id])

    assert session_id in results
    assert results[session_id].input_tokens == _NEW_INPUT_TOKENS


async def test_calculate_agrees_with_calculate_many_against_real_sql(event_store) -> None:
    """The delegation is only worth anything if it holds against the database.

    `calculate` is documented as the one-element case of `calculate_many`. A
    stub cannot demonstrate that, because both paths read the same canned rows.
    """
    from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
        TimescaleSessionCostQuery,
    )

    session_id = f"sess-{uuid4()}"
    await _record_summary(event_store, session_id, _OLD_INPUT_TOKENS)
    await _record_summary(event_store, session_id, _NEW_INPUT_TOKENS)

    query = TimescaleSessionCostQuery(event_store.pool)
    one = await query.calculate(session_id)
    many = (await query.calculate_many([session_id]))[session_id]

    assert one is not None
    assert one.input_tokens == many.input_tokens == _NEW_INPUT_TOKENS
    assert one.total_cost_usd == many.total_cost_usd


async def test_a_page_of_sessions_each_get_their_own_newest_summary(event_store) -> None:
    """The batch must not let one session's newest row answer for another.

    `DISTINCT ON` groups by session_id; a missing group-by would collapse the
    page to a single row, and with one session in the fixture that would look
    correct.
    """
    from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
        TimescaleSessionCostQuery,
    )

    first = f"sess-{uuid4()}"
    second = f"sess-{uuid4()}"
    await _record_summary(event_store, first, _OLD_INPUT_TOKENS)
    await _record_summary(event_store, first, _NEW_INPUT_TOKENS)
    await _record_summary(event_store, second, 42)

    query = TimescaleSessionCostQuery(event_store.pool)
    results = await query.calculate_many([first, second])

    assert results[first].input_tokens == _NEW_INPUT_TOKENS
    assert results[second].input_tokens == 42
