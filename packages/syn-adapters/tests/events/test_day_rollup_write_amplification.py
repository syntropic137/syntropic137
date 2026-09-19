"""The rollup trigger does not rewrite a row it cannot change (#1371).

WHAT IT COST

Every row inserted into ``agent_events`` fires one upsert into
``agent_event_day_rollup``. The first event for a
``(day, session_id, execution_id)`` triple inserts its row. Every event after
it conflicted, and the ``DO UPDATE`` then wrote:

    first_time = LEAST(agent_event_day_rollup.first_time, EXCLUDED.first_time)
    commits    = agent_event_day_rollup.commits + EXCLUDED.commits

For an event that is neither a commit nor earlier than what is stored, those
are ``LEAST(x, x)`` and ``x + 0`` - the values already in the row. PostgreSQL
has no way to notice that. An UPDATE writing identical values is still a new
tuple, still new index entries pointing at it, still WAL for both, and still a
dead tuple for vacuum to collect later.

WHICH EVENTS THAT IS: nearly all of them. ``commits`` moves only for
``git_commit``, one event type out of the ~25 in ``syn_shared.events``, and the
high-volume ones - tool starts and completions, token usage, stream chunks -
are not it. ``first_time`` moves only for an event that predates every event
already seen for its triple, which after the first is the out-of-order
minority. So the suppressed case is the normal case, and the written case is
the exception.

WHAT THIS FILE CAN AND CANNOT SHOW

It pins the predicate. That the predicate actually suppresses the write - that
the stored tuple is not replaced - is a question only PostgreSQL can answer,
and it is answered in ``test_heatmap_rollup_reconciliation.py`` by watching
``xmin``, under the ``integration`` marker that does not gate a PR into
``main`` (ci.yml). ``pytest -m unit`` gates the PR, so the predicate is pinned
here: dropping it is a one-line edit that changes no result anywhere and would
otherwise be invisible until someone measured ingestion again.
"""

from __future__ import annotations

import pytest

from syn_adapters.events.schema import ROLLUP_TRIGGER_FUNCTION_SQL

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


#: The trigger's SQL with its alignment whitespace collapsed - the statement
#: lines up its `=` for readability and none of that is part of a claim.
_TRIGGER = " ".join(ROLLUP_TRIGGER_FUNCTION_SQL.split())

#: Where the suppression has to sit: a `WHERE` on the conflict action. The same
#: word on the INSERT itself would mean something else entirely.
_UPSERT = _TRIGGER.split("DO UPDATE", 1)[1]


class TestTheUpsertSkipsWritesItCannotChange:
    def test_the_conflict_action_is_conditional(self) -> None:
        assert " WHERE " in _UPSERT, (
            "the rollup's ON CONFLICT DO UPDATE is unconditional, so every "
            "event after the first for a triple rewrites the row with the "
            "values already in it - a tuple, its index entries and the WAL "
            "for both, per event (#1371)"
        )

    def test_it_writes_exactly_when_first_time_would_move_earlier(self) -> None:
        """Not ``<=``, and not ``<>``.

        ``<=`` would keep rewriting the row for every event sharing the stored
        instant, which is the amplification this removes. ``<>`` would be worse
        than useless: it fires for LATER events too, which are the common ones,
        and ``LEAST`` would then write back the value already there.
        """
        assert "EXCLUDED.first_time < agent_event_day_rollup.first_time" in _UPSERT

    def test_it_writes_when_the_event_is_a_commit(self) -> None:
        """``commits`` is the accumulating column, so a commit always moves it.

        Asserted against the increment the SET performs rather than against the
        event type: the trigger has already reduced ``git_commit`` to 1 and
        everything else to 0 by this point, and ``<> 0`` is that reduction read
        back. Suppressing on the event type instead would put the same
        condition in two places for a future edit to get half right.
        """
        assert "EXCLUDED.commits <> 0" in _UPSERT

    def test_the_two_conditions_are_an_OR(self) -> None:
        """Either one alone changes the row, so requiring both would lose data.

        An ``AND`` here silently drops every commit that is not also the
        earliest event of its triple - which is most commits, since a session
        rarely opens with one.
        """
        assert "first_time < agent_event_day_rollup.first_time OR EXCLUDED.commits" in _UPSERT

    def test_the_suppression_did_not_replace_the_arithmetic(self) -> None:
        """The SET still accumulates; the WHERE only decides whether to run it.

        A predicate that gated ``commits = EXCLUDED.commits`` instead would
        reset the count to 1 on every commit. The boundary is worth pinning
        because the reconciling backfill in the same module DOES assign
        EXCLUDED - correctly, because its EXCLUDED is a complete aggregate -
        and copying that here would be an easy, quiet mistake.
        """
        assert "commits = agent_event_day_rollup.commits + EXCLUDED.commits" in _TRIGGER
        assert (
            "first_time = LEAST(agent_event_day_rollup.first_time, EXCLUDED.first_time)" in _TRIGGER
        )
