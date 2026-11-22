"""Canonical totals name only the sessions of the groups they could not price (#2341).

``GET /metrics`` polls these totals. Every summary-less session - codex work,
a crash, a run still going - lands in a rate-priced group as often as an
unpriced one, and those sessions accumulate with history. Naming them in the
totals statement shipped every one on every poll, to be read only when the
group turned out to be unpriced. These tests read the statements ``totals()``
actually sends, through the #897 double.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from syn_domain.agent_event_span import UNBOUNDED_LOWER, UNBOUNDED_UPPER

from .test_897_canonical_totals_coverage import (
    RATED,
    UNRATED,
    _Cell,
    _Conn,
    _group,
    _service,
    _turns,
)

pytestmark = pytest.mark.unit


class _RecordingConn(_Conn):
    """Also keeps the totals statement, which the #897 double only answers."""

    totals_query: str = ""

    async def fetch(self, query: str, *args: object) -> list[dict[str, _Cell]]:
        if "summary_observations" in query:
            self.totals_query = query
        return await super().fetch(query, *args)


def _summary_less(prefix: str, n: int) -> list[str]:
    return [f"{prefix}-{i}" for i in range(n)]


async def test_a_priced_groups_sessions_never_leave_the_database() -> None:
    conn = _RecordingConn(
        totals=[
            _group(RATED, vendor_cost="0.50", summary_observations=4, turn_sessions=None),
            _group(
                RATED,
                vendor_cost=None,
                summary_observations=0,
                turn_sessions=_summary_less("codex", 5_000),
            ),
        ],
    )

    totals = await _service(conn).totals()

    assert totals.unpriced_observation_count == 0
    # No per-session aggregate in the statement every poll sends...
    assert "ARRAY_AGG" not in conn.totals_query.upper()
    # ...and nothing reads them afterwards either.
    assert conn.session_reads == []
    assert conn.turn_reads == []


async def test_only_the_unpriced_groups_sessions_are_named() -> None:
    conn = _RecordingConn(
        totals=[
            _group(
                RATED,
                vendor_cost=None,
                summary_observations=0,
                turn_sessions=_summary_less("priced", 5_000),
            ),
            _group(UNRATED, vendor_cost=None, summary_observations=1, turn_sessions=["u-1"]),
        ],
        turns=[_turns(UNRATED, 3)],
    )

    totals = await _service(conn).totals(execution_ids={"exec-1"})

    assert totals.unpriced_observation_count == 1 + 3
    [(_query, args)] = conn.session_reads
    # The execution filter keeps its $1; the unpriced groups follow it.
    assert args[0] == ["exec-1"]
    assert args[1:] == ([UNRATED], [None], [False])
    [(_query, turn_args)] = conn.turn_reads
    assert turn_args[0] == ["u-1"]


class _DayConn(_RecordingConn):
    """Answers the session read with the UTC days the day rollup files them under."""

    days: list[dict[str, _Cell | date]]

    async def fetch(self, query: str, *args: object) -> list[dict[str, _Cell]]:
        if "JOIN unnest(" in query:
            self.session_reads.append((query, args))
            return self.days  # type: ignore[return-value]  # a DATE column
        return await super().fetch(query, *args)


async def test_each_day_reads_only_its_own_sessions_and_chunk() -> None:
    """One branch per day, so no branch is planned against every chunk (#2341)."""
    conn = _DayConn(
        totals=[_group(UNRATED, vendor_cost=None, summary_observations=0, turn_sessions=None)],
        turns=[_turns(UNRATED, 7)],
    )
    conn.totals[0]["turn_session_count"] = 3
    conn.days = [
        {"day": date(2026, 10, 2), "sessions": ["c", "b"]},
        {"day": date(2026, 9, 30), "sessions": ["a"]},
        {"day": None, "sessions": ["unseen"]},
    ]

    totals = await _service(conn).totals(execution_ids={"exec-1"})

    assert totals.unpriced_observation_count == 7
    [(query, args)] = conn.turn_reads
    assert query.count("UNION ALL") == 2
    for n in range(3):
        assert f"session_id = ANY(${3 * n + 1})" in query
        assert f"time >= ${3 * n + 2} AND time < ${3 * n + 3}" in query
    assert query.count("execution_id = ANY($10)") == 3
    assert args == (
        ["a"],
        datetime(2026, 9, 30, tzinfo=UTC),
        datetime(2026, 10, 1, tzinfo=UTC),
        ["b", "c"],
        datetime(2026, 10, 2, tzinfo=UTC),
        datetime(2026, 10, 3, tzinfo=UTC),
        # The rollup never saw it: read unbounded, never dropped.
        ["unseen"],
        UNBOUNDED_LOWER,
        UNBOUNDED_UPPER,
        ["exec-1"],
    )
