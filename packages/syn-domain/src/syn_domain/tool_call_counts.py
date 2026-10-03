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

ONE RULE DECIDES BOTH OF THIS MODULE'S HALVES, and it is worth stating on its
own because getting it wrong is what produced every bug this file has had:

    **Migrations own the DDL. The read model owns the rows.**

DDL, first. ``SYN_SKIP_AUTO_CREATE_TABLES=true`` is a deployment saying "I
apply my own schema; do not invent tables under me" - and it means it, because
the role the application connects as may hold no CREATE privilege at all, in
which case a stray ``CREATE TABLE IF NOT EXISTS`` is not a harmless no-op but
a startup that dies. So under that flag this module issues no DDL whatsoever.
It checks that migration 004 has been applied and says so plainly if it has
not, which is a better failure than either inventing the table or carrying on
against one that is not there.

Rows, second, and the mirror image. Migration 004 creates the tables and
stops. It does NOT backfill, and the reason is subtle enough to be worth the
paragraph: a migration runs while the PREVIOUS version of the application is
still up, and that version does not maintain this tally. Anything it appends
to ``agent_events`` between the backfill and the new binary's first breath is
counted in the history and missing from the tally. A migration-backfilled
table is therefore populated, plausible, and wrong - and "populated" was the
only question startup used to ask, so nothing ever repaired it. Undercounting
forever, with no blank table and no log line to give it away.

What replaces that question is ``agent_tool_call_counts_version``: a stamp
written by ``rebuild``, and by nothing else. Its presence means "a writer that
maintains this tally reconstructed these rows at definition version N". A
migration cannot write it, because a migration is not that writer. So the
first startup after the upgrade finds no stamp, recounts once, stamps, and is
cheap on every startup after. Bump ``TALLY_VERSION`` and the same thing
happens again, everywhere, exactly once - which is the guarantee every other
read model here gets free from its checkpoint version, and this one cannot,
because its ``handle_event`` is a no-op and a first registration has no
checkpoint to mismatch.

One honest limit on that guarantee: the recount happens during the new
application's startup, so it covers everything the old writer appended before
it stopped. A deployment that runs both versions against one database
concurrently can still have the old one append after the stamp lands. The
topology this ships in replaces the container rather than overlapping it, and
for anything that does overlap, ``rebuild_projection tool_call_counts`` or
``scripts/backfill/rebuild_tool_call_counts.py`` is the recount to run once
the last legacy writer is down.
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

#: The table this module owns. Created by migration 004, and by
#: ``ensure_ready`` when - and only when - the deployment has asked for tables
#: to be auto-created.
TABLE = "agent_tool_call_counts"

#: Where ``rebuild`` records the definition version it last recounted to. A
#: separate table rather than a column on the tally, because it says something
#: about the tally as a whole and there is exactly one of it.
VERSION_TABLE = "agent_tool_call_counts_version"

#: The migration that creates both tables. Named in the error a deployment
#: gets when it has not been applied, so the message is actionable.
MIGRATION = "004_tool_call_counts.sql"

#: What a stored row MEANS. Bump it when that changes - a different event type
#: counted, a different key, a corrected ``COALESCE`` - and every deployment
#: recounts once on its next startup instead of serving rows built to the old
#: definition. This is the tally's equivalent of a projection version, and
#: ``ToolCallCountsProjection.VERSION`` is deliberately the same number: there
#: is one definition of these rows, so there is one version of it.
TALLY_VERSION = 1

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

#: One row, enforced by the schema rather than by everyone who writes it: the
#: key is a boolean that is CHECKed to be true, so a second row is a constraint
#: violation and ``SELECT rebuilt_version FROM ...`` cannot be ambiguous.
CREATE_VERSION_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    rebuilt_version INTEGER NOT NULL
)
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

#: The stamp, read. ``None`` when nothing has ever recounted these rows, which
#: is what a migration-created table looks like and is the whole point of it.
_STAMPED_VERSION_SQL = f"SELECT rebuilt_version FROM {VERSION_TABLE}"

#: The stamp, written. Only ``rebuild`` runs this, and only inside the
#: transaction that recounted - see ``rebuild``.
_STAMP_SQL = f"""
INSERT INTO {VERSION_TABLE} (singleton, rebuilt_version)
VALUES (TRUE, $1)
ON CONFLICT (singleton) DO UPDATE SET rebuilt_version = EXCLUDED.rebuilt_version
"""

#: Does a table exist, without creating it. ``to_regclass`` resolves through
#: ``search_path`` exactly as the module's other statements do, so this asks
#: about the table those statements would reach and not a same-named one
#: somewhere else. Returns NULL rather than raising for an absent relation,
#: which is why it is this and not a ``SELECT`` against the table itself.
_TABLE_EXISTS_SQL = "SELECT to_regclass($1) IS NOT NULL"

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


class ToolCallCountsNotMigratedError(RuntimeError):
    """Auto-creation is off and the tally's tables are not there."""

    def __init__(self, table: str) -> None:
        super().__init__(
            f"Table '{table}' does not exist and SYN_SKIP_AUTO_CREATE_TABLES is set, "
            f"so this deployment owns its own DDL. Apply "
            f"packages/syn-adapters/src/syn_adapters/projection_stores/migrations/"
            f"{MIGRATION} before starting."
        )


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

    The stamp goes in the SAME transaction, and that is not tidiness. Split
    out, a crash between the recount and the stamp leaves one of two states,
    and one of them is unrecoverable by any later startup: stamped rows that
    were never recounted. Committed together, the only state a crash can leave
    is "correct rows, no stamp" - which the next startup fixes by recounting
    again, and recounting twice is recounting once.
    """
    async with conn.transaction():
        await conn.execute(_TRUNCATE_SQL)
        await conn.execute(BACKFILL_SQL, TOOL_EXECUTION_COMPLETED, NO_EXECUTION)
        await conn.execute(_STAMP_SQL, TALLY_VERSION)


async def ensure_ready(conn: SqlConnection, *, skip_auto_create: bool) -> None:
    """Make the tally fit to read, without deciding who owns the schema.

    Two questions that used to be one, and were wrong in opposite directions
    each time they shared a switch. "Do these tables exist" is the deployment's
    business and ``skip_auto_create`` is its answer. "Do these rows mean what
    this version of the code says they mean" is this module's business and no
    flag gets a vote on it. So the repair below runs in every configuration,
    and the DDL above runs in exactly one.

    ``skip_auto_create`` is required, with no default, on purpose. The two
    regressions here were both a caller not saying which policy it was under:
    once the repair inherited the DDL branch and production silently skipped
    it, once the DDL escaped the branch and ran against roles that may not hold
    CREATE. A default would be a third way to not say.

    Raises:
        ToolCallCountsNotMigratedError: auto-creation is off and the tables are
            not there. Loud, at startup, naming the migration - as against
            creating them anyway (the deployment said not to) or carrying on
            (every read of the tally is about to fail on a missing relation).
    """
    if skip_auto_create:
        await _require_migration_applied(conn)
    else:
        await conn.execute(CREATE_TABLE_SQL)
        await conn.execute(CREATE_INDEX_SQL)
        await conn.execute(CREATE_VERSION_TABLE_SQL)

    if await _needs_reconstruction(conn):
        await rebuild(conn)


async def _require_migration_applied(conn: SqlConnection) -> None:
    """Check both tables are there, creating nothing.

    The DDL-free half of ``ensure_ready``. A role with no CREATE privilege can
    run every statement this issues.
    """
    for table in (TABLE, VERSION_TABLE):
        if not await conn.fetchval(_TABLE_EXISTS_SQL, table):
            raise ToolCallCountsNotMigratedError(table)


async def _needs_reconstruction(conn: SqlConnection) -> bool:
    """Is a full recount owed? Two states say yes, for two different reasons.

    **Never recounted at this definition.** No stamp means these rows came
    from something that is not a writer of this tally: migration 004's table,
    a restore, a hand ``INSERT``. A stamp below ``TALLY_VERSION`` means they
    were built to an older definition of what a row is. Neither is detectable
    by looking at the rows - a wrong tally is full of perfectly ordinary
    numbers - which is why the stamp exists at all, and why "is it populated"
    was never a safe question to decide this on.

    **Blank with history behind it.** The stamp survives a bare ``TRUNCATE``
    of the tally, so it cannot be the only test: someone truncates the table,
    the stamp still reads 1, and every session reports zero tool calls
    indefinitely. Blank is the other yes, and it is qualified by whether there
    is anything to count so a fresh install is not condemned to probe
    ``agent_events`` on every startup it ever has.

    Cheap in the case that matters, which is the steady one: a stamped,
    populated tally costs a single-row read and one index probe that stops at
    the first row.
    """
    if await conn.fetchval(_STAMPED_VERSION_SQL) != TALLY_VERSION:
        return True
    if not await conn.fetchval(_TALLY_IS_BLANK_SQL):
        return False
    return bool(await conn.fetchval(_HISTORY_HAS_TOOL_CALLS_SQL, TOOL_EXECUTION_COMPLETED))


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

    #: The definition version of the rows, shared with ``ensure_ready``'s
    #: stamp rather than tracked twice. A bump here recounts on the next
    #: startup (the stamp no longer matches) as well as through the
    #: coordinator's version check, which is one number meaning one thing.
    VERSION = TALLY_VERSION

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
