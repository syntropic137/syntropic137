"""Canonical totals count the work they could not price, from the rows they priced (#897).

``GET /metrics`` reads its money and its coverage here. The count has to come
from the same groups the cost does, and it has to stay ONE aggregate when
nothing is unpriced: a per-execution read of all history is what took the
global card from 22ms to 684ms at p95.

The double answers each statement by a fragment of its text and records what
it was asked, which is all these tests need from Postgres. The SQL itself is
exercised against TimescaleDB by the integration suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions import CostCalculator, zero_usage_group_by
from syn_domain.contexts.agent_sessions.recorded_model_rows import (
    HAS_REQUESTED_MODEL_COLUMN,
    REQUESTED_MODEL_COLUMN,
)
from syn_domain.contexts.agent_sessions.slices.canonical_totals import query_service
from syn_domain.contexts.agent_sessions.slices.canonical_totals.query_service import (
    CanonicalUsageQueryService,
)

pytestmark = pytest.mark.unit

UNRATED = "mystery-model-1"
RATED = "claude-sonnet-4-5-20250929"

type _Cell = int | str | bool | Decimal | list[str] | None


def _group(
    model: str,
    *,
    vendor_cost: str | None,
    summary_observations: int,
    turn_sessions: list[str] | None,
) -> dict[str, _Cell]:
    """One (model, cost-nullness) group of ``_TOTALS_QUERY``."""
    return {
        "model": model,
        REQUESTED_MODEL_COLUMN: None,
        HAS_REQUESTED_MODEL_COLUMN: False,
        "vendor_cost_usd": None if vendor_cost is None else Decimal(vendor_cost),
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "summary_observations": summary_observations,
        "turn_session_count": len(turn_sessions or []),
        # Not a column: what the session read answers for this group.
        "turn_sessions": turn_sessions,
    }


def _turns(model: str, observations: int) -> dict[str, _Cell]:
    """One model's row of ``_UNPRICED_TURNS_QUERY``."""
    return {
        "model": model,
        REQUESTED_MODEL_COLUMN: None,
        HAS_REQUESTED_MODEL_COLUMN: False,
        "observations": observations,
    }


@dataclass
class _Conn:
    totals: list[dict[str, _Cell]]
    turns: list[dict[str, _Cell]] = field(default_factory=list)
    turn_reads: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    session_reads: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def _sessions_of(self, *keys: object) -> list[dict[str, _Cell]]:
        """The summary-less sessions of the groups bound by their model columns.

        All under one NULL day: the day rollup has seen none of them.
        """
        bound = set(zip(*keys, strict=True))  # type: ignore[call-overload]  # three parallel lists
        sessions = [
            session
            for row in self.totals
            if row["vendor_cost_usd"] is None
            and (row["model"], row[REQUESTED_MODEL_COLUMN], row[HAS_REQUESTED_MODEL_COLUMN])
            in bound
            for session in row["turn_sessions"] or []  # type: ignore[union-attr]  # list[str] | None
        ]
        return [{"day": None, "sessions": sessions}] if sessions else []

    async def fetch(self, query: str, *args: object) -> list[dict[str, _Cell]]:
        if "summary_observations" in query:
            return self.totals
        if "JOIN unnest(" in query:
            self.session_reads.append((query, args))
            return self._sessions_of(*args[-3:])
        if "AS observations" in query:
            self.turn_reads.append((query, args))
            return self.turns
        return []

    async def fetchrow(self, query: str, *args: object) -> dict[str, _Cell]:
        return {"sessions": 1}

    async def execute(self, query: str, *args: object) -> str:
        return ""

    def transaction(self, *, isolation: str, readonly: bool) -> _Block:
        return _Block()


class _Block:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@dataclass
class _Acquire:
    conn: _Conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@dataclass
class _Pool:
    conn: _Conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def _service(conn: _Conn) -> CanonicalUsageQueryService:
    return CanonicalUsageQueryService(_Pool(conn), CostCalculator())  # type: ignore[arg-type]  # a double for asyncpg.Pool


async def test_unpriced_summaries_and_turns_are_counted_beside_the_money() -> None:
    conn = _Conn(
        totals=[
            _group(RATED, vendor_cost="1.25", summary_observations=4, turn_sessions=None),
            _group(UNRATED, vendor_cost=None, summary_observations=2, turn_sessions=["s-3"]),
        ],
        # s-3 also ran turns on the rated model: priced work, so not counted.
        turns=[_turns(UNRATED, 5), _turns(RATED, 9)],
    )

    totals = await _service(conn).totals()

    assert totals.cost_usd == Decimal("1.25")
    assert totals.unpriced_observation_count == 2 + 5
    assert totals.unpriced_tokens == 110
    [(_query, args)] = conn.turn_reads
    assert args[0] == ["s-3"]


async def test_two_unpriced_groups_each_add_their_own_count() -> None:
    conn = _Conn(
        totals=[
            _group(UNRATED, vendor_cost=None, summary_observations=3, turn_sessions=None),
            _group(
                "mystery-model-2", vendor_cost=None, summary_observations=0, turn_sessions=["s-9"]
            ),
        ],
        turns=[_turns("mystery-model-2", 6)],
    )

    totals = await _service(conn).totals()

    assert totals.unpriced_observation_count == 3 + 6


async def test_priced_history_is_one_aggregate_and_reads_no_turns() -> None:
    """The latency guarantee: nothing unpriced, no read of agent_events at all."""
    conn = _Conn(
        totals=[
            _group(RATED, vendor_cost="0.50", summary_observations=4, turn_sessions=None),
            # Turn-priced on a rated model: priced, so its sessions are not read.
            _group(RATED, vendor_cost=None, summary_observations=0, turn_sessions=["s-1"]),
        ],
    )

    totals = await _service(conn).totals()

    assert totals.unpriced_observation_count == 0
    assert conn.turn_reads == []


async def test_a_workflows_turns_are_narrowed_to_its_executions() -> None:
    conn = _Conn(
        totals=[_group(UNRATED, vendor_cost=None, summary_observations=0, turn_sessions=["s-3"])],
        turns=[_turns(UNRATED, 5)],
    )

    totals = await _service(conn).totals(execution_ids={"exec-1"})

    assert totals.unpriced_observation_count == 5
    [(query, args)] = conn.turn_reads
    assert "execution_id = ANY($4)" in query
    assert args[3] == ["exec-1"]


def test_zero_token_turns_are_not_counted() -> None:
    """A turn reporting no tokens is a priced zero at any rate (#890).

    The rollup's ``observations`` counts it, which is why the count is read
    from agent_events with this predicate rather than from the rollup.
    """
    assert f"AND NOT {zero_usage_group_by()}" in query_service._UNPRICED_TURNS_DAY
