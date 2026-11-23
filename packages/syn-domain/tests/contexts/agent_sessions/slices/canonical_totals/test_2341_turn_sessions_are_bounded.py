"""Canonical totals name only the sessions of the groups they could not price (#2341).

``GET /metrics`` polls these totals. Every summary-less session - codex work,
a crash, a run still going - lands in a rate-priced group as often as an
unpriced one, and those sessions accumulate with history. Naming them in the
totals statement shipped every one on every poll, to be read only when the
group turned out to be unpriced. These tests read the statements ``totals()``
actually sends, through the #897 double.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
import sys
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.agent_event_span import UNBOUNDED_LOWER, UNBOUNDED_UPPER
from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.agent_sessions.recorded_model_rows import (
    HAS_REQUESTED_MODEL_COLUMN,
    REQUESTED_MODEL_COLUMN,
)
from syn_domain.contexts.agent_sessions.slices.canonical_totals import query_service

from .test_897_canonical_totals_coverage import (
    RATED,
    UNRATED,
    _Cell,
    _Conn,
    _group,
    _Pool,
    _service,
    _turns,
)

if TYPE_CHECKING:
    from types import ModuleType

pytestmark = pytest.mark.unit

_MODEL_KEYS = (REQUESTED_MODEL_COLUMN, HAS_REQUESTED_MODEL_COLUMN)

# The reader /metrics served before #2341, kept verbatim beside the scale test
# that compares whole responses against it. Loaded by path: it lives in the
# syn-api integration suite, which no unit module can import by name.
_FROZEN_PATH = (
    Path(__file__).resolve().parents[7]
    / "apps/syn-api/tests/integration/legacy_canonical_totals_pre_2341.py"
)


@cache
def _frozen_reader() -> ModuleType:
    spec = importlib.util.spec_from_file_location("legacy_canonical_totals_pre_2341", _FROZEN_PATH)
    assert spec is not None and spec.loader is not None, _FROZEN_PATH
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses resolve their annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    # The statement every poll sends is asked to list no model's sessions...
    [(_query, args)] = conn.session_reads
    assert args == ([], [], [])
    # ...and nothing reads them afterwards either.
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
    """Answers the totals statement's listing with the UTC days the day rollup files them under."""

    days: list[dict[str, _Cell | date]]

    async def fetch(self, query: str, *args: object) -> list[dict[str, _Cell]]:
        rows = await super().fetch(query, *args)
        if "summary_observations" in query:
            return [row for row in rows if row["sessions"] is None] + self.days  # type: ignore[operator]  # a DATE column
        return rows


def _day_conn(days: list[dict[str, _Cell | date]]) -> _DayConn:
    conn = _DayConn(
        totals=[_group(UNRATED, vendor_cost=None, summary_observations=0, turn_sessions=["x"])],
        turns=[_turns(UNRATED, 7)],
    )
    model = {key: _turns(UNRATED, 0)[key] for key in ("model", *_MODEL_KEYS)}
    conn.days = [{**model, **day} for day in days]
    return conn


async def test_each_session_day_is_read_within_its_own_day() -> None:
    conn = _day_conn(
        [
            {"day": date(2026, 10, 2), "sessions": ["c", "b"]},
            {"day": date(2026, 9, 30), "sessions": ["a"]},
            {"day": None, "sessions": ["unseen"]},
        ]
    )

    totals = await _service(conn).totals(execution_ids={"exec-1"})

    assert totals.unpriced_observation_count == 7
    [(query, args)] = conn.turn_reads
    assert "execution_id = ANY($4)" in query
    assert args == (
        ["a", "b", "c", "unseen"],
        [
            datetime(2026, 9, 30, tzinfo=UTC),
            datetime(2026, 10, 2, tzinfo=UTC),
            datetime(2026, 10, 2, tzinfo=UTC),
            # The rollup never saw it: read unbounded, never dropped.
            UNBOUNDED_LOWER,
        ],
        [
            datetime(2026, 10, 1, tzinfo=UTC),
            datetime(2026, 10, 3, tzinfo=UTC),
            datetime(2026, 10, 3, tzinfo=UTC),
            UNBOUNDED_UPPER,
        ],
        ["exec-1"],
    )


_AGENT_EVENTS = re.compile(r"\b(?:from|join)\s+agent_events\b", re.IGNORECASE)


@pytest.mark.parametrize("day_count", [1, 16, 91])
async def test_the_turns_read_names_agent_events_once_whatever_the_day_count(
    day_count: int,
) -> None:
    """One agent_events reference and one text, so planning does not grow with days.

    One UNION ALL branch per day re-planned every branch against every chunk
    under force_custom_plan: 29ms of planning for 7ms of execution at 16 days,
    and a text that varied with the day count (#2341).
    """
    conn = _day_conn(
        [
            {"day": date(2026, 1, 1) + timedelta(days=n), "sessions": [f"s-{n}"]}
            for n in range(day_count)
        ]
    )

    await _service(conn).totals()

    [(query, args)] = conn.turn_reads
    assert len(_AGENT_EVENTS.findall(query)) == 1, query
    assert query == query_service._UNPRICED_TURNS_QUERY.format(where="TRUE")
    assert len(args) == 3
    assert len(args[0]) == day_count  # type: ignore[arg-type]  # a list of session ids


_CANONICAL_USAGE_CTE = "canonical_usage AS ("


@pytest.mark.parametrize("execution_ids", [None, {"exec-1"}])
async def test_canonical_usage_is_evaluated_once_per_request(
    execution_ids: set[str] | None,
) -> None:
    """The totals and the unpriced sessions come from one evaluation of the CTE.

    Listing the sessions in a second statement evaluated the whole canonical
    decision again, the request's most expensive CTE, only to name them (#2341).
    """
    conn = _RecordingConn(
        totals=[
            _group(
                RATED,
                vendor_cost=None,
                summary_observations=0,
                turn_sessions=_summary_less("priced", 3),
            ),
            _group(UNRATED, vendor_cost=None, summary_observations=1, turn_sessions=["u-1"]),
        ],
        turns=[_turns(UNRATED, 3)],
    )

    totals = await _service(conn).totals(execution_ids=execution_ids)

    assert totals.unpriced_observation_count == 1 + 3
    evaluations = [query for query in conn.statements if _CANONICAL_USAGE_CTE in query]
    assert len(evaluations) == 1, conn.statements
    [(_query, turn_args)] = conn.turn_reads
    assert turn_args[0] == ["u-1"]


def _zero_total(model: str, sessions: list[str]) -> dict[str, _Cell]:
    """An unpriced group whose tokens sum to nothing."""
    group = _group(model, vendor_cost=None, summary_observations=0, turn_sessions=sessions)
    group["input_tokens"] = group["output_tokens"] = 0
    return group


@pytest.mark.parametrize(
    "nonzero_turns",
    [
        # Signed counts are accepted on the way in: +5 and -5 are two turns
        # that each reported tokens, in a group whose total is zero.
        2,
        # Two turns that reported nothing.
        0,
    ],
)
@pytest.mark.parametrize("execution_ids", [None, {"exec-1"}])
async def test_a_zero_total_unrated_group_counts_as_the_frozen_reader_counts(
    nonzero_turns: int, execution_ids: set[str] | None
) -> None:
    """A group pricing leaves nothing unpriced never had its turns read (#2341).

    Binding every unrated model before the totals come back named this group's
    sessions too, and counting them reported 2 observations behind 0 unpriced
    tokens, where the reader /metrics served before reported 0.
    """
    totals = [_zero_total(UNRATED, ["zero-sum"])]
    turns = [_turns(UNRATED, nonzero_turns)]
    candidate = _Conn(totals=totals, turns=turns)
    frozen = _Conn(totals=totals, turns=turns)

    actual = await _service(candidate).totals(execution_ids=execution_ids)
    before = (
        await _frozen_reader()
        .PreBoundCanonicalUsageQueryService(_Pool(frozen), CostCalculator())
        .totals(execution_ids=execution_ids)
    )

    assert dataclasses.asdict(actual) == dataclasses.asdict(before)
    assert actual.unpriced_observation_count == 0
    # Nothing is left to count, so agent_events is not read at all.
    assert candidate.turn_reads == []


async def test_only_an_unpriced_groups_sessions_are_read_beside_a_zero_total_one() -> None:
    """The listing is per model: a zero-total model's sessions stay out of the read."""
    other = "mystery-model-2"
    totals = [
        _zero_total(other, ["zero-only"]),
        _group(UNRATED, vendor_cost=None, summary_observations=1, turn_sessions=["u-1"]),
    ]
    turns = [_turns(UNRATED, 3), _turns(other, 2)]
    candidate = _Conn(totals=totals, turns=turns)
    frozen = _Conn(totals=totals, turns=turns)

    actual = await _service(candidate).totals()
    before = (
        await _frozen_reader()
        .PreBoundCanonicalUsageQueryService(_Pool(frozen), CostCalculator())
        .totals()
    )

    assert dataclasses.asdict(actual) == dataclasses.asdict(before)
    assert actual.unpriced_observation_count == 1 + 3
    [(_query, turn_args)] = candidate.turn_reads
    assert turn_args[0] == ["u-1"]
