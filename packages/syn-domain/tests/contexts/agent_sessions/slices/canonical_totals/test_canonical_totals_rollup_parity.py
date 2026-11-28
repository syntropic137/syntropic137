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
  a turn reporting no tokens         an observation, but not a reported one
  priced and unpriced turns, 2 days  counted per model, never per session
  several sessions per execution     delegates
  a NULL and an EMPTY execution id   kept apart by NULLS NOT DISTINCT
  tool events in bulk                rows the new path must never read

and the rows arrive in FOUR batches, because each path into the rollup is
separate SQL that has to agree with the others:

  A  before the usage rollup exists      reaches it by the BACKFILL
  B  after it exists                     by the TRIGGER, onto keys A also wrote
  D  while the trigger is DISABLED       by the reconcile a restart runs
  E  after that reconcile                by the trigger again

B is written by the trigger as it stood BEFORE reported_observations
(ADR-079), on a rollup without the column, and the next start upgrades it:
that is the only way a key can balance on observations and still owe its
reported turns, which is what the backfill's widened keep condition is for.
More turns on A's keys then go through the new trigger before D, so the
reconcile subtracts reported turns the trigger already counted. Then an
older build's start puts 007's function back over the column and the mark,
turns arrive under it, and this build's next start must reconcile them.
Turns with counts beyond int4 go through the new trigger and through D.

The unpriced observation count has no pre-E1 twin. Its specification is the
reader /metrics served before #2341, which counted reported turns from
agent_events: ADR-079 slice 6 reads them from the rollup instead, and every
field must still match it, unfiltered, per workflow and for the empty set.

MARKED ``integration``: CI runs it on push to main, PRs into release and the
weekly cron, not on PRs into main.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
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


def _turn(
    session: str,
    execution: str | None,
    n: int,
    model: str,
    *,
    requested: bool,
    zero: bool = False,
) -> Row:
    payload = json.dumps(
        {
            "model": model,
            "input_tokens": 0 if zero else 100 + n,
            "output_tokens": 0 if zero else 7 + n % 5,
            "cache_creation_tokens": 0 if zero else 30 * (n % 3),
            "cache_read_tokens": 0 if zero else 900 + n,
            **({"requested_model": "sonnet"} if requested else {}),
        }
    )
    return Row(_T0 + timedelta(minutes=n), TOKEN_USAGE, session, execution, payload)


def _wide_turns(batch_rows: list[Row], index: int, offset: int) -> list[Row]:
    """Two turns beyond int4 on the key of an earlier batch's session ``index``.

    The token columns are bigint, so ingest accepts both: one count above 2^31,
    and two below it whose sum is not. The reported count must accept them too.
    """
    first = next(r for r in batch_rows if r.session_id.endswith(f"-sess-{index}"))
    wide = (
        {"input_tokens": 2**31},
        {"output_tokens": 2**30, "cache_read_tokens": 2**30},
    )
    return [
        Row(
            _T0 + timedelta(minutes=offset + i),
            TOKEN_USAGE,
            first.session_id,
            first.execution_id,
            json.dumps({"model": _MODELS[0], **tokens}),
        )
        for i, tokens in enumerate(wide)
    ]


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
        rows.append(_turn(session, execution, i, model, requested=i % 4 == 0, zero=i == 11))
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
            zero=i % 18 == 0,
        )
        for i, r in enumerate(batch_rows)
        if r.event_type == TOKEN_USAGE and i % 9 == 0
    ]


def _priced_and_unpriced_across_days(batch_rows: list[Row]) -> list[Row]:
    """Summary-less sessions with turns on a priced and an unpriced model, days apart.

    a-sess-0 is turns-only on rated models and a-sess-5 turns-only on the
    unrated one: each gains the other kind, two and three days later, and a
    zero-token turn on the unrated model.
    """
    by_session = {r.session_id: r.execution_id for r in batch_rows}
    day = 24 * 60
    return [
        _turn("a-sess-0", by_session["a-sess-0"], 2 * day, _MODELS[2], requested=False),
        _turn("a-sess-0", by_session["a-sess-0"], 2 * day + 1, _MODELS[2], requested=True),
        _turn(
            "a-sess-0", by_session["a-sess-0"], 2 * day + 2, _MODELS[2], requested=False, zero=True
        ),
        _turn("a-sess-5", by_session["a-sess-5"], 3 * day, _MODELS[0], requested=False),
    ]


def _trigger_function_before_reported_observations() -> str:
    """The trigger function as 007 shipped it: the specification of an old install."""
    from syn_adapters import projection_stores

    shipped = (
        Path(projection_stores.__file__).parent / "migrations/007_agent_usage_rollup.sql"
    ).read_text()
    start = shipped.index("CREATE OR REPLACE FUNCTION agent_usage_rollup_apply()")
    end = shipped.index("$$ LANGUAGE plpgsql;", start) + len("$$ LANGUAGE plpgsql;")
    return shipped[start:end]


async def _as_before_reported_observations(conn: asyncpg.Connection) -> None:
    """Put the rollup back as a pre-ADR-079 install had it: no column, the old trigger."""
    await conn.execute(_trigger_function_before_reported_observations())
    await conn.execute("ALTER TABLE agent_turn_usage_rollup DROP COLUMN reported_observations")


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
                await _as_before_reported_observations(conn)
                await copy_rows(
                    conn, [*_batch("b", range(40, 70)), *_more_turns_on(batch_a, 1_000)]
                )
                await EventStoreSchema().ensure_schema(conn)  # upgrades: adds and backfills
                await copy_rows(
                    conn, [*_more_turns_on(batch_a, 1_500), *_wide_turns(batch_a, 0, 1_500)]
                )
                # An older build starts, and replaces the function, not the
                # column or the mark; then this build starts again.
                await conn.execute(_trigger_function_before_reported_observations())
                await copy_rows(conn, _more_turns_on(batch_a, 1_750))
                await EventStoreSchema().ensure_schema(conn)  # reconciles that body's turns
                await conn.execute(
                    f"ALTER TABLE agent_events DISABLE TRIGGER {USAGE_ROLLUP_TRIGGER}"
                )
                await copy_rows(
                    conn,
                    [
                        *_batch("d", range(70, 90)),
                        *_more_turns_on(batch_a, 2_000),
                        *_wide_turns(batch_a, 1, 2_000),
                    ],
                )
                await EventStoreSchema().ensure_schema(conn)  # a disabled trigger: reconcile
                await copy_rows(
                    conn,
                    [
                        *_batch("e", range(90, 104)),
                        *_more_turns_on(batch_a, 3_000),
                        *_priced_and_unpriced_across_days(batch_a),
                    ],
                )
            yield Seeded(pool=pool)
        finally:
            await pool.close()


#: Fields the post-E1 totals carry that the frozen pre-E1 specification never
#: had. Each needs its own proof elsewhere; this list is the conscious record.
_FIELDS_ADDED_AFTER_E1 = ("unpriced_observation_count",)


async def _assert_same_totals(pool: asyncpg.Pool, execution_ids: set[str] | None) -> object:
    """Run both reads, compare every field, and hand back the old totals."""
    from syn_domain.contexts.agent_sessions import CanonicalUsageQueryService, CostCalculator

    new = await CanonicalUsageQueryService(pool, CostCalculator()).totals(execution_ids)
    old = await LegacyCanonicalUsageQueryService(pool, CostCalculator()).totals(execution_ids)
    names = [f.name for f in dataclasses.fields(old)]
    new_names = [f.name for f in dataclasses.fields(new)]
    # The frozen legacy read is the specification for every field it has, and
    # each one must still match. A field added after E1 has no legacy twin, so
    # it is named here on purpose: adding another one must fail until someone
    # decides how it is proven (#897 added the observation count, which #2338
    # pins against its own fixtures).
    assert [n for n in new_names if n not in names] == list(_FIELDS_ADDED_AFTER_E1)
    assert [n for n in new_names if n in names] == names
    differing = {
        name: (getattr(old, name), getattr(new, name))
        for name in names
        if getattr(old, name) != getattr(new, name)
    }
    assert not differing, f"(old, new) per field: {differing}"
    await _assert_same_coverage(pool, execution_ids, new)
    return old


async def _assert_same_coverage(
    pool: asyncpg.Pool, execution_ids: set[str] | None, new: object
) -> None:
    """Every field, the observation count included, as the pre-#2341 reader said it."""
    from syn_domain.contexts.agent_sessions import CostCalculator

    from .test_2341_turn_sessions_are_bounded import _frozen_reader

    before = (
        await _frozen_reader()
        .PreBoundCanonicalUsageQueryService(pool, CostCalculator())
        .totals(execution_ids)
    )
    assert dataclasses.asdict(new) == dataclasses.asdict(before)  # type: ignore[call-overload]  # both are the totals dataclasses


async def test_unfiltered_totals_match_field_by_field(seeded: Seeded) -> None:
    old = await _assert_same_totals(seeded.pool, None)
    assert isinstance(old, LegacyCanonicalTotals)
    # The comparison must be about something: every field the card shows is live.
    assert old.sessions == 104
    assert old.cache_creation_tokens > 0
    assert old.cache_read_tokens > 0
    assert old.cost_usd > 0
    assert old.unpriced_tokens > 0
    # The seed has a model with no rate card and real tokens, so the new read
    # must report unpriced work too - a zero here would be the #890 lie.
    from syn_domain.contexts.agent_sessions import CanonicalUsageQueryService, CostCalculator

    new = await CanonicalUsageQueryService(seeded.pool, CostCalculator()).totals(None)
    assert new.unpriced_observation_count > 0


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS))
async def test_each_workflows_totals_match_field_by_field(seeded: Seeded, workflow: str) -> None:
    old = await _assert_same_totals(seeded.pool, set(WORKFLOWS[workflow]))
    assert isinstance(old, LegacyCanonicalTotals)
    assert old.sessions > 0
    assert old.input_tokens > 0
    if workflow in {"wf-a", "wf-b"}:  # a-sess-0's and a-sess-5's executions
        from syn_domain.contexts.agent_sessions import CanonicalUsageQueryService, CostCalculator

        new = await CanonicalUsageQueryService(seeded.pool, CostCalculator()).totals(
            set(WORKFLOWS[workflow])
        )
        assert new.unpriced_observation_count > 0


async def test_an_execution_set_matching_nothing_matches_too(seeded: Seeded) -> None:
    old = await _assert_same_totals(seeded.pool, {"exec-none"})
    assert isinstance(old, LegacyCanonicalTotals)
    assert old.sessions == 0


# Per turn key: the token_usage events that reported tokens, and the rollup's
# reported count, summed over its trigger and backfill rows. Spelled out here
# rather than imported, so the check does not share the predicate it checks.
_REPORTED_PER_KEY = """
WITH raw AS (
    SELECT session_id, execution_id, data->>'model' AS model,
        data->>'requested_model' AS requested_model, (data ? 'requested_model') AS has_rm,
        COUNT(*) FILTER (WHERE
            COALESCE((data->>'input_tokens')::bigint, 0)
            + COALESCE((data->>'output_tokens')::bigint, 0)
            + COALESCE((data->>'cache_creation_tokens')::bigint, 0)
            + COALESCE((data->>'cache_read_tokens')::bigint, 0) <> 0
        ) AS reported,
        COUNT(*) AS turns
    FROM agent_events WHERE event_type = 'token_usage'
    GROUP BY 1, 2, 3, 4, 5
), rolled AS (
    SELECT session_id, execution_id, model, requested_model, has_requested_model AS has_rm,
        SUM(reported_observations) AS reported, SUM(observations) AS turns
    FROM agent_turn_usage_rollup
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    (SELECT COUNT(*) FROM (SELECT * FROM raw EXCEPT SELECT * FROM rolled) a) AS missing,
    (SELECT COUNT(*) FROM (SELECT * FROM rolled EXCEPT SELECT * FROM raw) b) AS extra,
    (SELECT SUM(turns) - SUM(reported) FROM raw) AS zero_turns,
    (SELECT COUNT(*) FROM agent_turn_usage_rollup WHERE backfilled AND observations = 0
        AND reported_observations > 0) AS owed_only
"""


async def test_reported_observations_are_the_non_zero_turns_per_key(seeded: Seeded) -> None:
    """ADR-079 D1: every path into the rollup counts a turn as reported iff it had tokens.

    Batches A, B, D and E each reach the rollup by a different path, and B's
    keys reach the column only through the upgrade's widened backfill.
    """
    async with seeded.pool.acquire() as conn:
        row = await conn.fetchrow(_REPORTED_PER_KEY)
    assert row is not None
    assert (row["missing"], row["extra"]) == (0, 0), dict(row)
    # About something: the seed has zero-token turns, and keys that balanced on
    # observations and were owed only their reported turns (the upgrade).
    assert row["zero_turns"] > 0
    assert row["owed_only"] > 0
