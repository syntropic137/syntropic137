"""Canonical totals name only the sessions of the groups they could not price (#2341).

``GET /metrics`` polls these totals. Every summary-less session - codex work,
a crash, a run still going - lands in a rate-priced group as often as an
unpriced one, and those sessions accumulate with history. Naming them in the
totals statement shipped every one on every poll, to be read only when the
group turned out to be unpriced. These tests read the statements ``totals()``
actually sends, through the #897 double.
"""

from __future__ import annotations

import pytest

from .test_897_canonical_totals_coverage import (
    RATED,
    UNRATED,
    _Conn,
    _group,
    _service,
    _turns,
)

pytestmark = pytest.mark.unit


class _RecordingConn(_Conn):
    """Also keeps the totals statement, which the #897 double only answers."""

    totals_query: str = ""

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:  # type: ignore[override]
        if "summary_observations" in query:
            self.totals_query = query
        return await super().fetch(query, *args)  # type: ignore[return-value]


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
