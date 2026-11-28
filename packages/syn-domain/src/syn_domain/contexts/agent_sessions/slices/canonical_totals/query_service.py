"""All-time usage totals read from the one canonical source (issue #932).

The dashboard's metric card and its activity heatmap answered the same
question from different lanes - the card from Lane 1 ``SessionCompleted``
domain events, the heatmap from Lane 2 observations - and so quoted
9,151,116 tokens beside 10,002,629 for the same reality. This service gives
the card the SAME numbers the heatmap reads, so the two agree by
construction rather than by coincidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import asyncpg

    from syn_domain.contexts.agent_sessions.canonical_usage import PricingResolver

from syn_domain import agent_event_span
from syn_domain.contexts.agent_sessions.canonical_usage import (
    CANONICAL_MODEL_COLUMNS,
    TURN_USAGE_ROLLUP_TABLE,
    price_canonical_row,
    rate_for_row,
    rollup_usage_sources,
)
from syn_domain.contexts.agent_sessions.recorded_model_rows import (
    HAS_REQUESTED_MODEL_COLUMN,
    REQUESTED_MODEL_COLUMN,
    ModelRow,
)
from syn_domain.storable_text import pg_safe
from syn_shared.pricing import canonical_cost_usd, parse_vendor_cost

# All-time totals are read from the usage rollup, never from agent_events.
#
# Read from agent_events they were a scan of every usage row ever recorded:
# the hypertable is compressed and segmented by session_id, and nothing here
# names a session, so every compressed chunk was decompressed and every JSONB
# blob parsed, on every dashboard load (1.9s live, 3.0s with a workflow
# filter). The rollup holds one row per summary and one per (session, model)
# of turns, so this grows with sessions, not with telemetry. The decision
# between summary and turns is still CANONICAL_USAGE_DECISION_CTE's - the one
# the heatmap applies - so the card and the heatmap agree by construction.
_EXECUTION_FILTER = "execution_id = ANY($1)"

# The turn models that have no rate, decided BEFORE the totals statement, so
# that statement can count their summary-less sessions' turns itself. Read from the
# turn rollup alone, which is the canonical CTE's turn_usage source without the
# decision: one row per (session, execution, model), so it grows with sessions.
#
# A superset of what pricing the groups will find: it includes a model whose
# group's tokens total zero, and turns of sessions a summary superseded. So the
# count is per model, and only the models whose group pricing leaves tokens
# unpriced have their count kept. A zero total does not mean every turn was
# zero - signed counts are accepted, and +5 and -5 total nothing - and such a
# group has never contributed turns to the count.
_TURN_MODELS_QUERY = f"""
SELECT DISTINCT {CANONICAL_MODEL_COLUMNS}
FROM {TURN_USAGE_ROLLUP_TABLE}
WHERE {{where}}
"""

# Grouped by model AND cost-nullness for the same reason every other canonical
# query is: a group mixing priced and unpriced rows prices some of its tokens
# and not others, and reports the shortfall as though it were cheap (#788).
#
# summary_observations is what an UNPRICED group's observation count is made
# of (#897), read from the same rows as its money: a summary that won its
# session is one observation. A session with no summary contributes its turns
# that reported tokens. The rollup's ``observations`` counts zero-token turns
# too - a priced zero at any rate (#890) - so they are its
# ``reported_observations``, which the trigger and the backfill keep with the
# same predicate agent_events was once read with (ADR-079 D8 slice 6).
#
# The rows after UNION ALL are those counts, per model, for the summary-less
# sessions of the unrated turn models bound after the execution filter's $1
# and no other. They come from this statement, not a second one, so the
# canonical CTE is evaluated once per request: the transaction is READ ONLY,
# so there is nowhere to keep it between two. A reported row is the one with
# ``reported_observations``; its sums are NULL, and a totals row's
# ``reported_observations`` is. NOT DISTINCT, because a missing model is the
# commonest unpriced group and NULL = NULL matches nothing.
_TOTALS_QUERY = f"""
WITH {{sources}}
SELECT
    {CANONICAL_MODEL_COLUMNS},
    SUM(vendor_cost_usd) AS vendor_cost_usd,
    SUM(input_tokens) AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(cache_creation_tokens) AS cache_creation_tokens,
    SUM(cache_read_tokens) AS cache_read_tokens,
    COUNT(*) FILTER (
        WHERE session_id IN (SELECT session_id FROM priced_summary)
    ) AS summary_observations,
    NULL::bigint AS reported_observations
FROM canonical_usage
GROUP BY {CANONICAL_MODEL_COLUMNS}, (vendor_cost_usd IS NULL)
UNION ALL
SELECT
    turns.model, turns.{REQUESTED_MODEL_COLUMN}, turns.{HAS_REQUESTED_MODEL_COLUMN},
    NULL, NULL, NULL, NULL, NULL, NULL,
    SUM(turns.reported_observations)::bigint
FROM {TURN_USAGE_ROLLUP_TABLE} AS turns
JOIN unnest({{keys}}) AS unpriced({CANONICAL_MODEL_COLUMNS})
  ON turns.model IS NOT DISTINCT FROM unpriced.model
 AND turns.{REQUESTED_MODEL_COLUMN} IS NOT DISTINCT FROM unpriced.{REQUESTED_MODEL_COLUMN}
 AND turns.{HAS_REQUESTED_MODEL_COLUMN} = unpriced.{HAS_REQUESTED_MODEL_COLUMN}
WHERE {{where}}
  AND turns.session_id NOT IN (SELECT session_id FROM priced_summary)
GROUP BY turns.model, turns.{REQUESTED_MODEL_COLUMN}, turns.{HAS_REQUESTED_MODEL_COLUMN}
"""

type _ModelKey = tuple[object, object, bool]
"""A row's three model columns, as the canonical query groups on them."""


def _model_key(row: ModelRow) -> _ModelKey:
    return (
        row.get("model"),
        row.get(REQUESTED_MODEL_COLUMN),
        bool(row.get(HAS_REQUESTED_MODEL_COLUMN)),
    )


# Counts every session the canonical source knows about, including ones that
# produced no tokens. `canonical_usage` only carries sessions with usage rows,
# so a session that failed before the agent ran would be missed by counting
# there - which is exactly how two different session counts arose.
#
# Asked of agent_event_day_rollup, which has a row for every (day, session,
# execution) that emitted ANY event - the same population a COUNT(DISTINCT)
# over agent_events saw, at one row per session-day instead of one per event.
_SESSION_COUNT_QUERY = """
SELECT COUNT(DISTINCT session_id) AS sessions
FROM agent_event_day_rollup
WHERE {where}
"""


@dataclass(frozen=True)
class CanonicalTotals:
    """Every token and dollar the canonical source knows about."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    unpriced_tokens: int = 0
    unpriced_observation_count: int = 0
    """Observations behind ``unpriced_tokens``: the work ``cost_usd`` could not
    price, counted from the same rows. Non-zero means the cost is a lower bound,
    not that the work was free (#890, #897)."""
    sessions: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of the four buckets. Safe because they are disjoint."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass(frozen=True)
class PricingGroupRow:
    """One pricing group's sums: the grain ``_sum_groups`` prices at.

    A group is the three model columns and whether a vendor cost was reported
    (#788). The field names are the canonical columns', so ``asdict`` is the
    row ``price_canonical_row`` takes.
    """

    model: str | None
    requested_model: str | None
    has_requested_model: bool
    vendor_cost_usd: Decimal | None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    summary_observations: int
    """Winning summaries in the group: one observation each (#897)."""
    reported_observations: int = 0
    """Turns of the group's summary-less sessions that reported tokens. Read
    only where pricing leaves the group's tokens unpriced, so a source may
    leave it 0 on every other group."""


class UsageTotalsSource(Protocol):
    """Where the totals' pricing groups come from (ADR-079 D8).

    The reader prices whatever groups it is handed, so a source can change
    how the sums are kept without the money changing how it is decided.
    """

    async def group_rows(
        self, snapshot: agent_event_span.SpanConnection
    ) -> Sequence[PricingGroupRow]: ...


def _group_key(group: PricingGroupRow) -> _ModelKey:
    return (group.model, group.requested_model, group.has_requested_model)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _pricing_group(row: agent_event_span.SpanRow) -> PricingGroupRow:
    return PricingGroupRow(
        model=_optional_text(row["model"]),
        requested_model=_optional_text(row[REQUESTED_MODEL_COLUMN]),
        has_requested_model=bool(row[HAS_REQUESTED_MODEL_COLUMN]),
        vendor_cost_usd=parse_vendor_cost(row["vendor_cost_usd"]),
        input_tokens=int(row["input_tokens"]),  # type: ignore[arg-type]  # a SUM(bigint) column
        output_tokens=int(row["output_tokens"]),  # type: ignore[arg-type]  # a SUM(bigint) column
        cache_creation_tokens=int(row["cache_creation_tokens"]),  # type: ignore[arg-type]  # a SUM(bigint) column
        cache_read_tokens=int(row["cache_read_tokens"]),  # type: ignore[arg-type]  # a SUM(bigint) column
        summary_observations=int(row["summary_observations"] or 0),  # type: ignore[arg-type]  # a COUNT(*) column
    )


class CanonicalUsageQueryService:
    """Reads system-wide totals from the canonical usage definition."""

    def __init__(self, pool: asyncpg.Pool, cost_calculator: PricingResolver) -> None:
        """Takes the resolver rather than importing one.

        CostCalculator lives in the session_cost slice; importing it here
        would be a cross-slice dependency, which VSA forbids. The composition
        root supplies it.
        """
        self._pool = pool
        self._cost_calculator = cost_calculator

    @staticmethod
    def _render(template: str, filtered: bool, **fields: str) -> str:
        where = _EXECUTION_FILTER if filtered else "TRUE"
        return template.format(
            sources=rollup_usage_sources(where),
            model_columns=CANONICAL_MODEL_COLUMNS,
            where=where,
            **fields,
        )

    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        """Canonical totals, optionally narrowed to a set of executions.

        agent_events holds every id in its stored (sanitised) form, because
        AgentEvent's validator applies pg_safe on the way in. A read binds text
        against those columns, so it has to ask for the same spelling or it
        matches nothing and reports that as "nothing was recorded" (#1241).
        The usage rollup copies its ids from those rows, so the same holds.
        """
        stored_ids = [pg_safe(eid) for eid in execution_ids] if execution_ids is not None else None
        source: UsageTotalsSource = SessionGrainUsageSource(self._cost_calculator, stored_ids)
        sessions_sql = self._render(_SESSION_COUNT_QUERY, stored_ids is not None)

        # One snapshot for every read (#983), so the tokens and the session
        # count describe the same moment: two autocommit statements could
        # report a new session's tokens without the session, or the reverse.
        async with self._pool.acquire() as conn, agent_event_span.custom_plans(conn):  # type: ignore[arg-type]  # asyncpg generates PoolConnectionProxy's methods at runtime
            groups = await source.group_rows(conn)  # type: ignore[arg-type]  # asyncpg generates PoolConnectionProxy's methods at runtime
            session_row = await conn.fetchrow(
                sessions_sql, *([stored_ids] if stored_ids is not None else [])
            )

        return replace(
            self._sum_groups(groups),
            sessions=int(session_row["sessions"]) if session_row else 0,
        )

    def _sum_groups(self, groups: Iterable[PricingGroupRow]) -> CanonicalTotals:
        """The groups priced and summed, counting the observations behind unpriced tokens."""
        input_tokens = output_tokens = cache_creation = cache_read = 0
        unpriced = unpriced_observations = 0
        cost = Decimal("0")
        for group in groups:
            input_tokens += group.input_tokens
            output_tokens += group.output_tokens
            cache_creation += group.cache_creation_tokens
            cache_read += group.cache_read_tokens
            row_cost = price_canonical_row(asdict(group), self._cost_calculator)
            cost += row_cost.cost
            unpriced += row_cost.unpriced_tokens
            if row_cost.unpriced_tokens:
                unpriced_observations += group.summary_observations + group.reported_observations
        return CanonicalTotals(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            # A Decimal sum keeps its operands' exponent; report the canonical form.
            cost_usd=canonical_cost_usd(cost),
            unpriced_tokens=unpriced,
            unpriced_observation_count=unpriced_observations,
        )


@dataclass(frozen=True)
class SessionGrainUsageSource:
    """Today's groups: the canonical decision over the usage rollup, per session.

    A group pricing leaves unpriced has its reported turns counted from the
    turn rollup's ``reported_observations``, for that group's summary-less
    sessions only (#2341, ADR-079 D8 slice 6).
    """

    cost_calculator: PricingResolver
    execution_ids: Sequence[str] | None
    """Already in their stored spelling (``pg_safe``); None reads every one."""

    async def group_rows(self, snapshot: agent_event_span.SpanConnection) -> list[PricingGroupRow]:
        args = [list(self.execution_ids)] if self.execution_ids is not None else []
        keys = sorted(await self._unrated_turn_models(snapshot, args), key=repr)
        first = len(args) + 1
        rows = await snapshot.fetch(
            self._render(
                _TOTALS_QUERY,
                keys=f"${first}::text[], ${first + 1}::text[], ${first + 2}::boolean[]",
            ),
            *args,
            [key[0] for key in keys],
            [key[1] for key in keys],
            [key[2] for key in keys],
        )
        groups = [_pricing_group(row) for row in rows if row["reported_observations"] is None]
        unpriced = {
            _group_key(group)
            for group in groups
            if price_canonical_row(asdict(group), self.cost_calculator).unpriced_tokens
        }
        # Only the groups pricing leaves unpriced: the bound models are a
        # superset, and a zero-total group has never contributed turns.
        reported = {
            _model_key(row): int(row["reported_observations"])  # type: ignore[arg-type]  # asyncpg Record reads by name; a SUM(bigint) cast back
            for row in rows
            if row["reported_observations"] is not None and _model_key(row) in unpriced  # type: ignore[arg-type]  # asyncpg Record reads by name
        }
        # A vendor cost always prices, so a model's turns can only be unpriced
        # in its NULL-cost group: the one they are summed into.
        return [
            replace(group, reported_observations=reported.get(_group_key(group), 0))
            if group.vendor_cost_usd is None
            else group
            for group in groups
        ]

    def _render(self, template: str, **fields: str) -> str:
        return CanonicalUsageQueryService._render(  # the one rendering of the filter
            template, self.execution_ids is not None, **fields
        )

    async def _unrated_turn_models(
        self, conn: agent_event_span.SpanConnection, args: list[list[str]]
    ) -> set[_ModelKey]:
        """The turn models pricing has no rate for, as the totals statement binds them."""
        rows = await conn.fetch(self._render(_TURN_MODELS_QUERY), *args)
        return {
            _model_key(row)  # type: ignore[arg-type]  # asyncpg Record reads by name
            for row in rows
            if rate_for_row(row, self.cost_calculator) is None  # type: ignore[arg-type]  # asyncpg Record reads by name
        }
