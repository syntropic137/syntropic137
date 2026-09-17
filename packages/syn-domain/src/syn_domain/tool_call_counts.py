"""How many tool calls a session, or an execution, has made.

The answer used to be recomputed on every page load::

    SELECT session_id, COUNT(*) FROM agent_events
    WHERE session_id = ANY($1::text[]) AND event_type = 'tool_execution_completed'
    GROUP BY session_id

``agent_events`` is a COMPRESSED TimescaleDB hypertable segmented by
``session_id`` and ordered by ``time``. ``event_type`` is in neither, so no
index can be consulted for it inside a compressed chunk: the predicate is
evaluated by decompressing every segment belonging to every session on the
page. Measured on the selfhost VPS at 219,140 rows, sixteen sessions cost
60,562 buffer hits and 905ms, and three copies of that query stacked up
behind a dashboard that polls faster than it answers (#1322). The shape is
unbounded by anything except how much the agents have done, which is why it
was fine at 20k rows and is not at 219k.

So the count is not derived on the read path any more. It is a tally, kept
incrementally as the observations are written and read back from a small
ordinary table - the read model answers reads, which is how the rest of this
system already works.

    session_id | execution_id | tool_calls

One row per (session, execution) pair rather than per session, because
``agent_events.execution_id`` is nullable and nothing constrains a session to
one execution; keying on the pair lets BOTH questions be a plain ``SUM``
over the same rows instead of one of them needing a special case. An event
that carried no execution is stored with ``execution_id = ''``, which is what
``NOT NULL`` in a key costs and is the only sentinel here: ``by_execution``
never returns it, exactly as the old ``WHERE execution_id IS NOT NULL`` never
counted it.

Nothing outside this module knows the table exists. It owns its DDL, its
one-time backfill, the write that maintains it and the two reads that consume
it, so the storage decision can change without any caller changing with it.

The tally is maintained in the SAME transaction as the insert it counts
(see ``syn_adapters.events.store_write``). It therefore cannot drift from
``agent_events``: either both land or neither does. ``BACKFILL_SQL`` is the
definition of the tally and can be re-run against a truncated table at any
time to prove that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_shared.events import TOOL_EXECUTION_COMPLETED

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: The table this module owns. Created by ``ensure_ready`` and mirrored, for
#: installs that apply migrations by hand, in
#: ``syn_adapters/projection_stores/migrations/004_tool_call_counts.sql``.
TABLE = "agent_tool_call_counts"

#: ``execution_id`` for an observation that carried no execution. The column is
#: part of the key and a key cannot be NULL; this is that, and nothing else.
NO_EXECUTION = ""

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    tool_calls BIGINT NOT NULL,
    PRIMARY KEY (session_id, execution_id)
)
"""

#: ``by_execution`` filters on ``execution_id``, which is the second column of
#: the primary key and so has no usable prefix in it.
CREATE_INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_tool_call_counts_execution
ON {TABLE} (execution_id)
"""

#: The definition of the tally, in one statement. Run once when the table is
#: first created, so an install that already has history does not report every
#: session as having made zero tool calls.
BACKFILL_SQL = f"""
INSERT INTO {TABLE} (session_id, execution_id, tool_calls)
SELECT session_id, COALESCE(execution_id, $2), COUNT(*)
FROM agent_events
WHERE event_type = $1
GROUP BY session_id, COALESCE(execution_id, $2)
ON CONFLICT (session_id, execution_id) DO UPDATE
SET tool_calls = EXCLUDED.tool_calls
"""

_RECORD_SQL = f"""
INSERT INTO {TABLE} (session_id, execution_id, tool_calls)
SELECT * FROM UNNEST($1::text[], $2::text[], $3::bigint[])
ON CONFLICT (session_id, execution_id) DO UPDATE
SET tool_calls = {TABLE}.tool_calls + EXCLUDED.tool_calls
"""

_BY_SESSION_SQL = f"""
SELECT session_id, SUM(tool_calls)::bigint AS cnt
FROM {TABLE}
GROUP BY session_id
"""

_BY_SESSION_IDS_SQL = f"""
SELECT session_id, SUM(tool_calls)::bigint AS cnt
FROM {TABLE}
WHERE session_id = ANY($1::text[])
GROUP BY session_id
"""

_BY_EXECUTION_SQL = f"""
SELECT execution_id, SUM(tool_calls)::bigint AS cnt
FROM {TABLE}
WHERE execution_id <> $1
GROUP BY execution_id
"""

_BY_EXECUTION_IDS_SQL = f"""
SELECT execution_id, SUM(tool_calls)::bigint AS cnt
FROM {TABLE}
WHERE execution_id = ANY($1::text[])
GROUP BY execution_id
"""


class SqlRow(Protocol):
    """A result row, read by column name."""

    def __getitem__(self, key: str, /) -> object: ...


class SqlConnection(Protocol):
    """The three things this module needs from a database connection.

    Narrower than ``asyncpg.Connection`` on purpose, and satisfied by it: it is
    what lets a test assert WHICH table the read path queried against a double,
    rather than needing a live TimescaleDB to find out.
    """

    async def execute(self, query: str, /, *args: object) -> str: ...

    async def fetch(self, query: str, /, *args: object) -> Sequence[SqlRow]: ...

    async def fetchval(self, query: str, /, *args: object) -> object: ...


@dataclass(frozen=True)
class ToolCallTally:
    """``tool_calls`` new tool calls observed for one (session, execution)."""

    session_id: str
    execution_id: str
    tool_calls: int


def tally(events: Iterable[tuple[str, str, str | None]]) -> list[ToolCallTally]:
    """Fold ``(event_type, session_id, execution_id)`` triples into tallies.

    Takes the three columns as they will be STORED rather than an event object:
    the writer's event model stays in the adapter package where it belongs, and
    a batch is counted from exactly the values about to be inserted, not from
    the dicts they were parsed out of. That is the hop at which a normalised
    event type, a sanitised id or a defaulted execution id goes missing, and a
    tally keyed differently from the row it counts is one no reader can find.
    """
    counts: dict[tuple[str, str], int] = {}
    for event_type, session_id, execution_id in events:
        if event_type != TOOL_EXECUTION_COMPLETED:
            continue
        key = (session_id, execution_id if execution_id is not None else NO_EXECUTION)
        counts[key] = counts.get(key, 0) + 1
    return [
        ToolCallTally(session_id=sid, execution_id=eid, tool_calls=count)
        for (sid, eid), count in counts.items()
    ]


async def ensure_ready(conn: SqlConnection) -> None:
    """Create the table, and backfill it once if this is the first time.

    Backfilling only on creation is what keeps the one expensive scan of
    ``agent_events`` to one, ever - asking "is the table empty?" instead would
    re-scan on every startup of an install whose agents have never used a tool,
    which is precisely the install that can least afford to be told it is fine.
    """
    already_there = bool(await conn.fetchval(f"SELECT to_regclass('{TABLE}') IS NOT NULL"))
    await conn.execute(CREATE_TABLE_SQL)
    await conn.execute(CREATE_INDEX_SQL)
    if not already_there:
        await conn.execute(BACKFILL_SQL, TOOL_EXECUTION_COMPLETED, NO_EXECUTION)


async def record(conn: SqlConnection, tallies: Sequence[ToolCallTally]) -> None:
    """Add ``tallies`` to the stored counts.

    Call inside the transaction that writes the observations being counted.
    """
    if not tallies:
        return
    await conn.execute(
        _RECORD_SQL,
        [t.session_id for t in tallies],
        [t.execution_id for t in tallies],
        [t.tool_calls for t in tallies],
    )


async def by_session(
    conn: SqlConnection, session_ids: Sequence[str] | None = None
) -> dict[str, int]:
    """Tool calls per session id. ``None`` asks about every session."""
    if session_ids is None:
        rows = await conn.fetch(_BY_SESSION_SQL)
    elif not session_ids:
        return {}
    else:
        rows = await conn.fetch(_BY_SESSION_IDS_SQL, list(session_ids))
    return _counts(rows, "session_id")


async def by_execution(
    conn: SqlConnection, execution_ids: Sequence[str] | None = None
) -> dict[str, int]:
    """Tool calls per execution id. ``None`` asks about every execution."""
    if execution_ids is None:
        rows = await conn.fetch(_BY_EXECUTION_SQL, NO_EXECUTION)
    elif not execution_ids:
        return {}
    else:
        rows = await conn.fetch(_BY_EXECUTION_IDS_SQL, list(execution_ids))
    return _counts(rows, "execution_id")


def _counts(rows: Sequence[SqlRow], key: str) -> dict[str, int]:
    """Index ``(key, cnt)`` result rows by their key."""
    return {str(row[key]): int(str(row["cnt"])) for row in rows}
