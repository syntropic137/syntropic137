"""The rollup's `day` is a UTC day, and the heatmap reads it as one (#1371).

WHAT WENT WRONG

``agent_event_day_rollup.day`` was written as ``time_bucket('1 day',
NEW.time)::date``. ``time_bucket`` over a ``timestamptz`` returns a
``timestamptz``, and casting one of those to ``date`` resolves in the
CONNECTION's ``TimeZone`` setting - which nothing in this system pins. asyncpg
inherits whatever the server defaults to.

That makes the stored day a fact about the WRITER rather than about the event.
Under ``America/Los_Angeles`` an event stamped ``2023-05-10T00:30Z`` is filed
under May 9. The trigger sees each event exactly once, so no later read can
notice or correct it: the row is wrong for as long as the database lives.

The same cast appeared on the READ side, as ``started_at::date``, where it
decides which day a session is counted on. A reader in a different zone from
the writer therefore attributed sessions to a day whose executions and commits
had been filed by a different rule.

WHY THIS IS A UNIT TEST, AND WHAT IT CANNOT DO

It asks what SQL the two sides are built from - not what PostgreSQL does with
it. The behavioural proof, three time zones against a real database, is
``test_heatmap_day_is_utc.py`` in syn-domain, and that job does not run on a
pull request into ``main`` (ci.yml: schedule, workflow_dispatch, push to main,
or a PR into ``release``). ``pytest -m unit`` is what gates the PR, so what has
to fit in it is the agreement itself: one definition, used on both sides, with
no bare cast left anywhere.

That agreement is the part a future edit is most likely to break, because the
two sides live in different packages and nothing but this file connects them.
"""

from __future__ import annotations

import re

import pytest

from syn_adapters.events.schema import (
    ROLLUP_BACKFILL_SQL,
    ROLLUP_TRIGGER_FUNCTION_SQL,
    utc_day,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    _COMMITS_QUERY,
    _EXECUTIONS_QUERY,
    _SESSIONS_QUERY,
    _USAGE_QUERY,
    _utc_day,
)

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


#: Every statement that decides which day something belongs to.
_DAY_BEARING_SQL = {
    "trigger": ROLLUP_TRIGGER_FUNCTION_SQL,
    "backfill": ROLLUP_BACKFILL_SQL,
    "sessions": _SESSIONS_QUERY,
    "usage": _USAGE_QUERY,
}


def _unpinned_casts(sql: str) -> list[str]:
    """Every ``::date`` in ``sql`` that could resolve in the session's zone.

    Two spellings are exempt, and only two:

      ``(... AT TIME ZONE 'UTC')::date``  the operand is a plain timestamp by
                                          then, so the cast has no zone left
                                          to consult
      ``$n::date``                        the operand is a bind parameter the
                                          driver already sends as a date; the
                                          cast only names its type

    Anything else is a ``timestamptz`` being turned into a day by whichever
    connection happens to run the statement, which is #1371. Returned with
    their context so a failure says WHERE, not just that there was one.
    """
    return [
        sql[max(0, cast.start() - 40) : cast.end()]
        for cast in re.finditer(r"::date", sql)
        if not sql[: cast.start()].endswith("AT TIME ZONE 'UTC')")
        and re.search(r"\$\d+$", sql[: cast.start()]) is None
    ]


class TestOneDefinitionOfADay:
    def test_the_two_sides_spell_it_identically(self) -> None:
        """The writer's ``utc_day`` and the reader's ``_utc_day`` are one rule.

        They cannot share a definition: the package dependency runs
        syn-adapters -> syn-domain, so the read side cannot import the write
        side's, and the write side has no business importing a heatmap slice.
        This assertion is what stands in for the import - if either is edited
        alone, the rollup's days and the heatmap's days part company and every
        number on the endpoint is quietly attributed to the wrong square.
        """
        for expr in ("NEW.time", "time", "started_at", "s.started_at", "MIN(x)"):
            assert _utc_day(expr) == utc_day(expr)

    def test_it_converts_before_it_casts(self) -> None:
        """Order is the whole mechanism, so it is asserted rather than assumed.

        ``AT TIME ZONE 'UTC'`` turns the instant into a plain ``timestamp``
        holding the UTC wall clock, and only a PLAIN timestamp's ``::date``
        is zone-free. Casting first and converting after would convert a value
        that had already lost the information.
        """
        assert utc_day("NEW.time") == "(NEW.time AT TIME ZONE 'UTC')::date"


class TestNothingIsLeftCastingInTheSessionZone:
    @pytest.mark.parametrize("sql", _DAY_BEARING_SQL.values(), ids=_DAY_BEARING_SQL.keys())
    def test_no_statement_casts_a_timestamp_in_the_connections_zone(self, sql: str) -> None:
        """#1371 in one assertion, wherever it is reintroduced.

        A bare ``::date`` is the defect whichever of the four statements grows
        one, and it is invisible in review precisely because it looks like a
        cast rather than like a decision.
        """
        leftovers = _unpinned_casts(sql)
        assert not leftovers, (
            "a day-bearing statement casts a timestamp to date without pinning "
            "the zone. That resolves in the connection's TimeZone, so the day "
            f"an event lands on depends on who was connected (#1371): {leftovers}"
        )

    def test_the_writer_no_longer_leans_on_time_bucket_for_the_day(self) -> None:
        """``time_bucket(...)::date`` was the original spelling of the bug.

        It looks safer than a bare cast - it names a bucket - and it is not:
        it hands back a ``timestamptz``, so the cast that follows is the same
        unpinned one. Kept as its own assertion because a future edit reaching
        for a bucketing function is exactly how it would come back.
        """
        assert "time_bucket" not in ROLLUP_TRIGGER_FUNCTION_SQL
        assert "time_bucket" not in ROLLUP_BACKFILL_SQL


class TestTheReadSideUsesIt:
    """The hop that matters: the definition reaching the queries that run."""

    def test_sessions_are_counted_on_the_utc_day_they_started(self) -> None:
        assert f"SELECT {utc_day('started_at')} AS day" in _SESSIONS_QUERY

    def test_usage_is_priced_onto_the_utc_day_its_session_started(self) -> None:
        assert f"{utc_day('s.started_at')} AS day" in _USAGE_QUERY

    @pytest.mark.parametrize(
        "sql",
        (_SESSIONS_QUERY, _EXECUTIONS_QUERY, _COMMITS_QUERY, _USAGE_QUERY),
        ids=("sessions", "executions", "commits", "usage"),
    )
    def test_the_window_bounds_compare_a_date_to_a_date(self, sql: str) -> None:
        """The bounds need no conversion, and must not grow one.

        ``day`` is a ``DATE`` column and ``$1``/``$2`` are dates, so the
        comparison already carries no zone. It is pinned here because the
        obvious "fix" for a zone bug is to wrap things in conversions, and
        wrapping THESE would introduce the very dependence the rest of this
        file removes.
        """
        assert "day >= $1::date" in sql
        assert "day <= $2::date" in sql
