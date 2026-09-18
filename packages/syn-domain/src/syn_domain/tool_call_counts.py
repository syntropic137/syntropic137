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
``agent_events``: either both land or neither does.

A derived table also has to be reconstructible, because the one thing worse
than a slow number is a confident wrong one. ``rebuild`` is that: it discards
the tally and recomputes it from ``agent_events``, and it is the only
definition of what the rows should be - ``ensure_ready`` calls it rather than
carrying a second copy of the same SELECT. A read model that survived a
projection rebuild still holding yesterday's numbers is the failure this
module is now built to prevent (#1322).

Being reconstructible is not the same as being reconstructed, and the two
places that have to reach ``rebuild`` are both here:

- ``ToolCallCountsProjection`` puts the tally in the coordinator's registry
  alongside every other read model, so a version bump or an operator's
  ``rebuild_projection`` recounts it instead of walking past it.
- ``ensure_ready`` runs at every startup, from ``AgentEventStore.initialize``.
  Deliberately NOT from the branch that auto-creates tables: production sets
  ``SYN_SKIP_AUTO_CREATE_TABLES=true``, so the deployment most likely to have
  had its tally emptied - by a rebuild, a restore, an operator - was the one
  configuration that skipped the repair. Creating tables and repairing a read
  model are different jobs and must not share a switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from event_sourcing import CheckpointedProjection, ProjectionResult

from syn_shared.events import TOOL_EXECUTION_COMPLETED

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from event_sourcing import (
        DispatchContext,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
    )

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

#: The definition of the tally, in one statement. The only place that says what
#: a stored row means, which is why ``rebuild`` runs exactly this and nothing
#: re-derives the count anywhere else.
BACKFILL_SQL = f"""
INSERT INTO {TABLE} (session_id, execution_id, tool_calls)
SELECT session_id, COALESCE(execution_id, $2), COUNT(*)
FROM agent_events
WHERE event_type = $1
GROUP BY session_id, COALESCE(execution_id, $2)
ON CONFLICT (session_id, execution_id) DO UPDATE
SET tool_calls = EXCLUDED.tool_calls
"""

#: Emptied with TRUNCATE rather than DELETE, and that choice is load-bearing:
#: see ``rebuild``.
_TRUNCATE_SQL = f"TRUNCATE TABLE {TABLE}"

#: Cheap: one index probe that stops at the first row, and only asked at all
#: when the tally is blank.
_TALLY_IS_BLANK_SQL = f"SELECT NOT EXISTS (SELECT 1 FROM {TABLE})"

#: "Is there anything to count?" - asked only of a blank tally, to tell an
#: install that has never run a tool apart from one whose tally was wiped.
_HISTORY_HAS_TOOL_CALLS_SQL = "SELECT EXISTS (SELECT 1 FROM agent_events WHERE event_type = $1)"

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


class SqlTransaction(Protocol):
    """An open transaction, released when the block exits."""

    async def __aenter__(self) -> object: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object, /) -> object: ...


class SqlConnection(Protocol):
    """The four things this module needs from a database connection.

    Narrower than ``asyncpg.Connection`` on purpose, and satisfied by it: it is
    what lets a test assert WHICH table the read path queried against a double,
    rather than needing a live TimescaleDB to find out.

    ``transaction`` is here because ``rebuild`` is not correct without one, and
    a module that needs atomicity should say so rather than smuggling ``BEGIN``
    through ``execute`` - which would silently commit a caller's open
    transaction along with its own.
    """

    async def execute(self, query: str, /, *args: object) -> str: ...

    async def fetch(self, query: str, /, *args: object) -> Sequence[SqlRow]: ...

    async def fetchval(self, query: str, /, *args: object) -> object: ...

    def transaction(self) -> SqlTransaction: ...


class SqlPoolAcquire(Protocol):
    """A borrowed connection, returned to the pool when the block exits."""

    async def __aenter__(self) -> SqlConnection: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object, /) -> object: ...


class SqlPool(Protocol):
    """A source of connections. ``asyncpg.Pool`` satisfies it.

    Here for the same reason ``SqlConnection`` is: the rebuild lifecycle hands
    this module no connection, only the pool it was wired with, and a double
    has to be able to stand in for it.
    """

    def acquire(self) -> SqlPoolAcquire: ...


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


async def rebuild(conn: SqlConnection) -> None:
    """Throw the tally away and recompute it from ``agent_events``.

    The repair for a tally that is blank, stale or wrong - a table someone
    truncated, a rebuild that wiped the read models, an import that wrote
    events by some path that did not keep the count. Always safe to run: the
    result depends on ``agent_events`` alone, never on what was there before,
    so running it twice is running it once.

    Atomic, so no reader ever sees the gap. TRUNCATE and the recount are one
    transaction, which is why a caller repairing a live deployment does not
    have to choose between a wrong number and no number.

    WHY TRUNCATE AND NOT DELETE, which is the part that is easy to "simplify"
    later and get wrong: TRUNCATE takes ACCESS EXCLUSIVE on the table, so a
    concurrent writer blocks at its own ``record`` - and since ``record``
    shares a transaction with the ``agent_events`` insert it counts, that
    writer cannot commit either. Its rows are therefore invisible to the
    recount below and its increment lands on top afterwards. DELETE takes a
    weaker lock, lets that writer commit in the middle, and loses its
    increment: the recount would overwrite the row from a snapshot taken
    before the event existed.
    """
    async with conn.transaction():
        await conn.execute(_TRUNCATE_SQL)
        await conn.execute(BACKFILL_SQL, TOOL_EXECUTION_COMPLETED, NO_EXECUTION)


async def ensure_ready(conn: SqlConnection) -> None:
    """Create the table if it is absent, and fill it if it is blank.

    One rule, not two: a tally with no rows in it is rebuilt, whether this is
    the first startup after the feature shipped or the first startup after
    someone truncated the table. The earlier "backfill only when the table did
    not exist" could not tell those apart, and answered the second with
    silence - every session reporting zero tool calls, indefinitely, with
    nothing in the logs and a number on the page that looked like a number.

    What this costs: when the tally IS blank, one probe of ``agent_events``
    for a single tool completion. That probe stops at the first matching row,
    so the install it could actually scan to the end of is the one that has
    never run a tool - and then it finds nothing, rebuilds nothing, and pays
    it again next startup. Once per process against a table read thousands of
    times per hour is the trade this whole module exists to make, in the other
    direction.

    What this does NOT catch is a tally that is populated and wrong - no
    probe can, short of the recount itself. ``rebuild`` is the answer to that
    one, and ``scripts/backfill/rebuild_tool_call_counts.py`` runs it.
    """
    await conn.execute(CREATE_TABLE_SQL)
    await conn.execute(CREATE_INDEX_SQL)
    if not await conn.fetchval(_TALLY_IS_BLANK_SQL):
        return
    if await conn.fetchval(_HISTORY_HAS_TOOL_CALLS_SQL, TOOL_EXECUTION_COMPLETED):
        await rebuild(conn)


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


#: The name the checkpoint store, ``/health`` and
#: ``SubscriptionCoordinator.rebuild_projection`` know this read model by.
PROJECTION_NAME = "tool_call_counts"


class ToolCallCountsNotWiredError(RuntimeError):
    """A rebuild was asked of a tally projection that has no database."""

    def __init__(self, projection_name: str) -> None:
        super().__init__(
            f"Projection '{projection_name}' was registered without a database pool, "
            "so its rebuild cannot recount from agent_events. Pass the observability "
            "pool to create_coordinator_service()."
        )


class ToolCallCountsProjection(CheckpointedProjection):
    """The tally's seat in the platform's projection-rebuild lifecycle.

    Every other read model here is rebuilt by replaying the event store into
    it. This one must not be. The count is written in the SAME transaction as
    the ``agent_events`` row it counts (``record``), so a replay that handled
    ``tool_execution_completed`` again would double every number. What the
    tally needs from the lifecycle is the other half of it: ``clear_all_data``,
    the hook the coordinator calls when a read model is to be discarded and
    rebuilt - on a version bump, and on an operator's ``rebuild_projection``.
    For this table "discard and rebuild" is one statement, and it already has a
    name: ``rebuild``.

    Registering it is the whole point. Before this, a platform rebuild reached
    twenty-four read models and silently skipped the twenty-fifth: the operator
    rebuilt the projections, this table kept whatever it held - often nothing,
    because the same rebuild had truncated it - and every session reported zero
    tool calls with nothing anywhere saying so.

    ``handle_event`` therefore SKIPs, which advances the checkpoint and touches
    no rows. The subscription is declared all the same, and declared as the one
    event the tally is derived from, because that is the true answer to "what
    feeds this read model" and it is what a reader of the registry needs. It is
    not a claim that the events are counted here; they are counted at the write
    that creates them, which is the property that makes this table incapable of
    drifting from ``agent_events`` in the first place.
    """

    VERSION = 1

    def __init__(self, pool: SqlPool | None = None) -> None:
        self._pool = pool

    def get_name(self) -> str:
        return PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return {TOOL_EXECUTION_COMPLETED}

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],  # noqa: ARG002
        checkpoint_store: ProjectionCheckpointStore,  # noqa: ARG002
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        """Nothing to do per event: this tool call was counted as it was stored.

        SKIP rather than SUCCESS so the coordinator advances the checkpoint
        itself. A projection that reported SUCCESS would be claiming it had
        saved a checkpoint, and this one has no reason to open a transaction.
        """
        return ProjectionResult.SKIP

    async def clear_all_data(self) -> None:
        """Recount from ``agent_events`` - the rebuild, in full.

        Emptying the table is what the coordinator asks of every other
        projection, because a replay is about to refill it. No replay will
        refill this one, so emptying alone would leave the deployment showing
        zero tool calls forever. ``rebuild`` empties and refills atomically,
        which is both halves in the one place they are already correct
        together.

        A projection wired with no pool cannot do it and says so. Silence here
        is the exact failure being fixed: the rebuild would report success and
        the read model would be wrong.
        """
        if self._pool is None:
            raise ToolCallCountsNotWiredError(PROJECTION_NAME)
        async with self._pool.acquire() as conn:
            await rebuild(conn)
