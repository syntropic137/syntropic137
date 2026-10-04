"""E1 changed what /metrics COSTS. This proves it did not change what it SAYS.

The mirror of test_heatmap_rollup_equivalence.py for the dashboard's metric
card. Before #1558, CanonicalUsageQueryService.totals() read agent_events.
It now reads the usage rollup (agent_summary_usage, agent_turn_usage_rollup)
and counts sessions from agent_event_day_rollup. Those tables are filled by
trigger and backfill SQL that only PostgreSQL runs, so the only proof that
the numbers did not move is to run both implementations against one database
and compare every field. legacy_canonical_totals_pre_e1.py is the frozen old
implementation: it is the specification.

COMPARED, field by field: input, output, cache-creation and cache-read
tokens, cost, unpriced tokens, and the session count. Unfiltered (the card),
and filtered to three workflows' execution sets (/metrics?workflow_id=, which
resolves a workflow to its executions and asks for exactly this), plus an
id that matches nothing.

WHAT IS SEEDED, AND WHY. Every shape is one the rollup could get wrong:

  two models in one session          the turn rollup's key carries the model
  requested_model present / absent   key presence is its own key column
  a zero-usage summary, then a real  the decision must still prefer usage
  two real summaries                 the most recent must win, not the sum
  a summary with no vendor cost      priced from tokens, a separate group
  a model with no rate card          unpriced tokens, not $0
  turns only, no summary             priced from the turns
  a session with no usage at all     counted as a session, with no tokens
  several sessions per execution     delegates
  a NULL and an EMPTY execution id   kept apart by NULLS NOT DISTINCT
  tool events in bulk                rows the new path must never read

and the rows arrive in FOUR batches, because each path into the rollup is
separate SQL that has to agree with the others:

  A  before the usage rollup exists      reaches it by the BACKFILL
  B  after it exists                     by the TRIGGER, onto keys A also wrote
  D  while the trigger is DISABLED       by the reconcile a restart runs
  E  after that reconcile                by the trigger again

MARKED ``integration``: CI runs it on push to main, PRs into release and the
weekly cron, not on PRs into main.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_shared.events import SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

from .legacy_canonical_totals_pre_e1 import (
    LegacyCanonicalTotals,
    LegacyCanonicalUsageQueryService,
)
from .usage_rollup_seed import (
    Row,
    copy_rows,
    prepare_pre_e1_schema,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = pytest.mark.integration

WORKFLOWS: dict[str, frozenset[str]] = {
    "wf-a": frozenset({"exec-0", "exec-1", "exec-2", "exec-3"}),
    "wf-b": frozenset({"exec-4", "exec-5", "exec-6", "exec-7"}),
    "wf-c": frozenset({"exec-8", "exec-9", "exec-10", "exec-11", ""}),
}

_T0 = datetime(2026, 9, 1, tzinfo=UTC)
_MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001", "mystery-model-x")


def _turn(session: str, execution: str | None, n: int, model: str, *, requested: bool) -> Row:
    payload = json.dumps(
        {
            "model": model,
            "input_tokens": 100 + n,
            "output_tokens": 7 + n % 5,
            "cache_creation_tokens": 30 * (n % 3),
            "cache_read_tokens": 900 + n,
            **({"requested_model": "sonnet"} if requested else {}),
        }
    )
    return Row(_T0 + timedelta(minutes=n), TOKEN_USAGE, session, execution, payload)


def _summary(
    session: str,
    execution: str | None,
    at: int,
    model: str,
    *,
    tokens: int,
    cost: float | None,
) -> Row:
    payload = json.dumps(
        {
            "model": model,
            "total_input_tokens": tokens,
            "total_output_tokens": tokens // 10,
            "cache_creation_tokens": tokens // 3,
            "cache_read_tokens": tokens * 4,
            **({"total_cost_usd": cost} if cost is not None else {}),
        }
    )
    return Row(_T0 + timedelta(hours=at), SESSION_SUMMARY, session, execution, payload)


def _tools(session: str, execution: str | None, count: int) -> list[Row]:
    return [
        Row(
            _T0 + timedelta(seconds=i),
            "tool_execution_completed",
            session,
            execution,
            json.dumps({"tool_name": "Bash", "tool_use_id": f"t{i}", "output": "x" * 50}),
        )
        for i in range(count)
    ]


def _session(batch: str, n: int, execution: str | None) -> list[Row]:
    """One session's events; the shape is chosen by ``n``."""
    session = f"{batch}-sess-{n}"
    rows = [Row(_T0, SESSION_STARTED, session, execution, "{}"), *_tools(session, execution, 6)]
    shape = n % 7
    if shape == 6:
        return rows  # no usage at all: still a session
    for i in range(12):
        model = _MODELS[(n + i // 6) % 2] if shape != 5 else _MODELS[2]
        rows.append(_turn(session, execution, i, model, requested=i % 4 == 0))
    if shape == 1:
        rows.append(_summary(session, execution, 1, _MODELS[0], tokens=0, cost=None))
        rows.append(_summary(session, execution, 2, _MODELS[0], tokens=5_000, cost=0.12))
    elif shape == 2:
        rows.append(_summary(session, execution, 1, _MODELS[1], tokens=9_000, cost=0.30))
        rows.append(_summary(session, execution, 3, _MODELS[1], tokens=4_000, cost=0.11))
    elif shape == 3:
        rows.append(_summary(session, execution, 2, _MODELS[0], tokens=3_000, cost=None))
    elif shape == 4:
        rows.append(_summary(session, execution, 2, _MODELS[1], tokens=2_000, cost=0.04))
    # shapes 0 and 5: turns only (5 on a model with no rate card)
    return rows


def _execution_of(n: int) -> str | None:
    if n % 13 == 12:
        return None
    if n % 13 == 11:
        return ""
    return f"exec-{n % 12}"


def _batch(batch: str, sessions: range) -> list[Row]:
    return [row for n in sessions for row in _session(batch, n, _execution_of(n))]


def _more_turns_on(batch_rows: list[Row], offset: int) -> list[Row]:
    """Extra turns on keys an earlier batch wrote, so two paths share one key."""
    return [
        _turn(
            r.session_id,
            r.execution_id,
            offset + i,
            str(json.loads(r.data)["model"]),
            requested=False,
        )
        for i, r in enumerate(batch_rows)
        if r.event_type == TOKEN_USAGE and i % 9 == 0
    ]


@dataclasses.dataclass
class Seeded:
    pool: asyncpg.Pool


@pytest.fixture
async def seeded(test_infrastructure) -> AsyncIterator[Seeded]:
    import asyncpg

    from syn_adapters.events.schema import USAGE_ROLLUP_TRIGGER, EventStoreSchema

    async with throwaway_database(test_infrastructure.timescaledb_url) as dsn:
        await prepare_pre_e1_schema(dsn)
        pool = await asyncpg.create_pool(dsn)
        assert pool is not None
        try:
            async with pool.acquire() as conn:
                batch_a = _batch("a", range(40))
                await copy_rows(conn, batch_a)
                await EventStoreSchema().ensure_schema(conn)  # creates and backfills
                await copy_rows(
                    conn, [*_batch("b", range(40, 70)), *_more_turns_on(batch_a, 1_000)]
                )
                await conn.execute(
                    f"ALTER TABLE agent_events DISABLE TRIGGER {USAGE_ROLLUP_TRIGGER}"
                )
                await copy_rows(
                    conn, [*_batch("d", range(70, 90)), *_more_turns_on(batch_a, 2_000)]
                )
                await EventStoreSchema().ensure_schema(conn)  # a disabled trigger: reconcile
                await copy_rows(
                    conn, [*_batch("e", range(90, 104)), *_more_turns_on(batch_a, 3_000)]
                )
            yield Seeded(pool=pool)
        finally:
            await pool.close()


async def _assert_same_totals(pool: asyncpg.Pool, execution_ids: set[str] | None) -> object:
    """Run both reads, compare every field, and hand back the old totals."""
    from syn_domain.contexts.agent_sessions import CanonicalUsageQueryService, CostCalculator

    new = await CanonicalUsageQueryService(pool, CostCalculator()).totals(execution_ids)
    old = await LegacyCanonicalUsageQueryService(pool, CostCalculator()).totals(execution_ids)
    names = [f.name for f in dataclasses.fields(old)]
    assert names == [f.name for f in dataclasses.fields(new)]
    differing = {
        name: (getattr(old, name), getattr(new, name))
        for name in names
        if getattr(old, name) != getattr(new, name)
    }
    assert not differing, f"(old, new) per field: {differing}"
    return old


async def test_unfiltered_totals_match_field_by_field(seeded: Seeded) -> None:
    old = await _assert_same_totals(seeded.pool, None)
    assert isinstance(old, LegacyCanonicalTotals)
    # The comparison must be about something: every field the card shows is live.
    assert old.sessions == 104
    assert old.cache_creation_tokens > 0
    assert old.cache_read_tokens > 0
    assert old.cost_usd > 0
    assert old.unpriced_tokens > 0


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS))
async def test_each_workflows_totals_match_field_by_field(seeded: Seeded, workflow: str) -> None:
    old = await _assert_same_totals(seeded.pool, set(WORKFLOWS[workflow]))
    assert isinstance(old, LegacyCanonicalTotals)
    assert old.sessions > 0
    assert old.input_tokens > 0


async def test_an_execution_set_matching_nothing_matches_too(seeded: Seeded) -> None:
    old = await _assert_same_totals(seeded.pool, {"exec-none"})
    assert isinstance(old, LegacyCanonicalTotals)
    assert old.sessions == 0
