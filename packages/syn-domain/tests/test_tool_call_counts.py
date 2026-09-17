"""The read path reports tool calls without asking ``agent_events`` (#1322).

The measured defect: every list endpoint derived its tool-call column with

    SELECT session_id, COUNT(*) FROM agent_events
    WHERE session_id = ANY($1) AND event_type = $2 GROUP BY session_id

``agent_events`` is a compressed hypertable segmented by ``session_id`` and
ordered by ``time``. ``event_type`` is in neither key, so no index inside a
compressed chunk can answer that filter and Postgres decompresses every
segment belonging to every session on the page: 60,562 buffer hits and 905ms
for sixteen sessions, against 219,140 rows. /sessions and /executions took
4-30 seconds.

So the load-bearing test here is not "the number is right" - the old query
also produced the right number. It is that **no read path asks
``agent_events`` for ``tool_execution_completed`` rows at all**, because
filtering that column is the only way to derive the count from raw events and
therefore the only way the 905ms comes back. A benchmark would not catch a
reintroduction; this does, with no database at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain import tool_call_counts
from syn_shared.events import TOOL_EXECUTION_COMPLETED

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

_SESSION = "sess-1322"
_EXECUTION = "exec-1322"


# --------------------------------------------------------------------------
# The tally itself
# --------------------------------------------------------------------------


def test_only_tool_completions_are_counted() -> None:
    """A tally that counted every event would be a row count, not a tool count."""
    tallies = tool_call_counts.tally(
        [
            (TOOL_EXECUTION_COMPLETED, _SESSION, _EXECUTION),
            ("tool_execution_started", _SESSION, _EXECUTION),
            ("token_usage", _SESSION, _EXECUTION),
            (TOOL_EXECUTION_COMPLETED, _SESSION, _EXECUTION),
        ]
    )

    assert tallies == [
        tool_call_counts.ToolCallTally(session_id=_SESSION, execution_id=_EXECUTION, tool_calls=2)
    ]


def test_the_same_session_under_two_executions_stays_two_tallies() -> None:
    """Both reads key off this table, so one key cannot serve the other.

    ``by_session`` sums over executions and ``by_execution`` sums over
    sessions, which only works while the row remembers both. A tally keyed by
    session alone would make every per-execution count wrong the moment an
    execution spans more than one session - which is the normal case.
    """
    tallies = tool_call_counts.tally(
        [
            (TOOL_EXECUTION_COMPLETED, _SESSION, "exec-a"),
            (TOOL_EXECUTION_COMPLETED, _SESSION, "exec-b"),
        ]
    )

    assert {t.execution_id: t.tool_calls for t in tallies} == {"exec-a": 1, "exec-b": 1}


def test_an_event_with_no_execution_is_still_counted_for_its_session() -> None:
    """``execution_id`` is part of the key and a key cannot be NULL.

    The count it replaced was a ``COUNT(*)`` with no join, so a tool call
    recorded outside any execution still reached the session's total. Dropping
    those rows here would silently lower every ad-hoc session's tool count.
    """
    tallies = tool_call_counts.tally([(TOOL_EXECUTION_COMPLETED, _SESSION, None)])

    assert tallies == [
        tool_call_counts.ToolCallTally(
            session_id=_SESSION,
            execution_id=tool_call_counts.NO_EXECUTION,
            tool_calls=1,
        )
    ]


# --------------------------------------------------------------------------
# Reads and writes, against a connection that records what it was asked
# --------------------------------------------------------------------------


class _Row:
    def __init__(self, key: str, value: str, count: int) -> None:
        self._cells: dict[str, object] = {key: value, "cnt": count}

    def __getitem__(self, key: str) -> object:
        return self._cells[key]


class _RecordingConnection:
    """Records every statement, and serves rows only to the tally's table.

    Serving by table rather than by SQL text is the point: a read path that
    went back to ``agent_events`` would get nothing here, and a test that
    matched on text would have to be rewritten - and could be rewritten - the
    moment someone changed the query.
    """

    def __init__(self, rows: Sequence[_Row] = (), *, table_exists: bool = True) -> None:
        self.statements: list[str] = []
        self.args: list[tuple[object, ...]] = []
        self._rows = list(rows)
        self._table_exists = table_exists

    def _record(self, query: str, args: tuple[object, ...]) -> None:
        self.statements.append(query)
        self.args.append(args)

    async def execute(self, query: str, *args: object) -> str:
        self._record(query, args)
        return "OK"

    async def fetch(self, query: str, *args: object) -> list[_Row]:
        self._record(query, args)
        if tool_call_counts.TABLE not in query:
            return []
        return self._rows

    async def fetchval(self, query: str, *args: object) -> object:
        self._record(query, args)
        return self._table_exists

    @property
    def tables_read(self) -> set[str]:
        return {
            word
            for statement in self.statements
            for word in ("agent_events", tool_call_counts.TABLE)
            if word in statement
        }


async def test_by_session_reads_the_tally_and_nothing_else() -> None:
    conn = _RecordingConnection([_Row("session_id", _SESSION, 10)])

    counts = await tool_call_counts.by_session(conn, [_SESSION])

    assert counts == {_SESSION: 10}
    assert conn.tables_read == {tool_call_counts.TABLE}


async def test_by_execution_reads_the_tally_and_nothing_else() -> None:
    conn = _RecordingConnection([_Row("execution_id", _EXECUTION, 7)])

    counts = await tool_call_counts.by_execution(conn, [_EXECUTION])

    assert counts == {_EXECUTION: 7}
    assert conn.tables_read == {tool_call_counts.TABLE}


async def test_asking_about_no_ids_asks_the_database_nothing() -> None:
    """An empty page is the common case on an idle dashboard.

    ``ANY('{}')`` would be a round trip whose answer is known before it is
    sent, and ``None`` already means "every id" - so the empty sequence cannot
    be folded into it without turning "nothing was asked for" into "ask for
    everything".
    """
    conn = _RecordingConnection()

    assert await tool_call_counts.by_session(conn, []) == {}
    assert await tool_call_counts.by_execution(conn, []) == {}
    assert conn.statements == []


async def test_record_adds_to_the_count_already_stored() -> None:
    """The write is an increment, not a set: events arrive in many batches.

    Asserted on the SQL because there is no database here to observe it in -
    and because ``DO UPDATE SET tool_calls = EXCLUDED.tool_calls`` is the
    plausible wrong spelling, which would make every batch after the first
    reset the session's total instead of adding to it.
    """
    conn = _RecordingConnection()

    await tool_call_counts.record(
        conn,
        [
            tool_call_counts.ToolCallTally(
                session_id=_SESSION, execution_id=_EXECUTION, tool_calls=3
            )
        ],
    )

    assert len(conn.statements) == 1
    assert "ON CONFLICT" in conn.statements[0]
    assert (
        f"SET tool_calls = {tool_call_counts.TABLE}.tool_calls + EXCLUDED.tool_calls"
        in (conn.statements[0])
    )
    assert conn.args[0] == ([_SESSION], [_EXECUTION], [3])


async def test_recording_nothing_writes_nothing() -> None:
    """Most batches contain no tool completions; none of them may cost a write."""
    conn = _RecordingConnection()

    await tool_call_counts.record(conn, [])

    assert conn.statements == []


async def test_a_new_install_backfills_from_the_history_it_already_has() -> None:
    """Without this, every existing session reports zero tool calls forever.

    The one scan of ``agent_events`` this fix is allowed: once, at the moment
    the table is created.
    """
    conn = _RecordingConnection(table_exists=False)

    await tool_call_counts.ensure_ready(conn)

    assert any("agent_events" in statement for statement in conn.statements), (
        "an install with history was left with an empty tally"
    )
    assert conn.args[-1][0] == TOOL_EXECUTION_COMPLETED


async def test_an_install_that_already_has_the_table_never_scans_again() -> None:
    """The scan is the cost being removed; paying it on every startup is not a fix."""
    conn = _RecordingConnection(table_exists=True)

    await tool_call_counts.ensure_ready(conn)

    assert not any("agent_events" in statement for statement in conn.statements)
