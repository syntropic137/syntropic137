"""Schema management for agent event store."""

from __future__ import annotations

import hashlib
import logging
import struct

import asyncpg

from syn_adapters.events.models import EXPECTED_COLUMNS
from syn_domain.contexts.agent_sessions import (
    SUMMARY_USAGE_TABLE,
    TURN_USAGE_ROLLUP_TABLE,
    USAGE_ROLLUP_STATE_TABLE,
    recorded_model_group_by,
    recorded_model_select,
    summary_usage_columns,
    turn_usage_columns,
)
from syn_shared.events import GIT_COMMIT, SESSION_SUMMARY, TOKEN_USAGE

logger = logging.getLogger(__name__)

# THE ROLLUP'S KEY, AND WHY IT IS A CONSTRAINT WITH NULLS NOT DISTINCT.
#
# `execution_id` is nullable, so the key has to say what two NULLs mean. A
# plain UNIQUE says "distinct", which would give unattributed telemetry one
# rollup row per event and lose the bound the whole table exists to provide.
# This key originally bought the opposite answer with an expression,
# `COALESCE(execution_id, '')` - and that also merged a genuine EMPTY-STRING
# execution id into the unattributed row, because COALESCE maps both to the
# same ''. Two rows that name different things became one (#1371).
#
# `NULLS NOT DISTINCT` (PostgreSQL 15+; production is 16.15) says exactly the
# intended thing and nothing more: NULL groups with NULL, '' groups with '',
# and the two never meet. It is also the grain ROLLUP_BACKFILL_SQL's
# `GROUP BY` already produced, so the backfill's own rows can no longer
# collide with each other on the way in.
#
# It is a CONSTRAINT rather than a bare index so both ON CONFLICT clauses can
# name it. `ON CONFLICT (day, session_id, execution_id)` would have to INFER
# an arbiter index, and inference matches on columns, so it cannot express
# "the NULLS NOT DISTINCT one" - a second unique index on these columns would
# make it ambiguous, and it gives a reader nothing to check the clause
# against. `ON CONFLICT ON CONSTRAINT agent_event_day_rollup_key` names the
# one object below, and fails loudly if it is ever not there.
#
# REPLACING IT ON A DATABASE THAT ALREADY HAS THE OLD ONE. Leaving both would
# leave the defect: the old expression index would go on merging NULL with ''
# whatever the new key says. So the old object is dropped and the new one
# added - guarded, because ALTER TABLE ... ADD CONSTRAINT has no IF NOT
# EXISTS and ensure_schema() runs at every API startup; unguarded, every
# restart would rebuild the index.
#
# The guard asks for the key we want (unique, on this name, nulls not
# distinct) rather than merely for the name, so a database holding the old
# expression index, a hand-made wrong one, or nothing at all all take the
# same path to the same place.
#
# SAFE WHILE THE TRIGGER IS LIVE, for two reasons that both matter:
#   - it runs inside _create_day_rollup's single transaction, which also
#     re-attaches the trigger and therefore holds SHARE ROW EXCLUSIVE on
#     agent_events. A concurrent insert blocks on that lock rather than
#     observing a rollup with no key at all.
#   - the new key is strictly FINER than the old one: any two rows the
#     COALESCE index kept apart differ under this one too. So the build
#     cannot fail on existing data, and no deployment needs a repair step.
ROLLUP_KEY_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_index i ON i.indexrelid = c.conindid
        WHERE c.conrelid = 'agent_event_day_rollup'::regclass
          AND c.conname = 'agent_event_day_rollup_key'
          AND c.contype = 'u'
          AND i.indnullsnotdistinct
    ) THEN
        RETURN;
    END IF;

    ALTER TABLE agent_event_day_rollup
        DROP CONSTRAINT IF EXISTS agent_event_day_rollup_key;
    DROP INDEX IF EXISTS agent_event_day_rollup_key;
    ALTER TABLE agent_event_day_rollup
        ADD CONSTRAINT agent_event_day_rollup_key
        UNIQUE NULLS NOT DISTINCT (day, session_id, execution_id);
END $$;
"""


def utc_day(timestamp_expr: str) -> str:
    """The UTC calendar day of a `timestamptz` SQL expression.

    THE ONE PLACE `day` IS DEFINED, and it is written in UTC on purpose
    (#1371).

    `some_timestamptz::date` - and equally `time_bucket('1 day', ts)::date`,
    because time_bucket hands back a timestamptz too - resolves in the
    CONNECTION's TimeZone setting. Nothing in this system pins that: asyncpg
    inherits whatever the server defaults to, and a self-hosted database
    defaulting to America/Los_Angeles would file an event stamped
    2023-05-10T00:30Z under May 9. The trigger sees each event exactly once, so
    that row is then wrong FOREVER - no later read can correct it, and the
    heatmap has no way to tell.

    `AT TIME ZONE 'UTC'` converts the instant to a plain `timestamp` holding
    the UTC wall clock first, and a plain timestamp's `::date` has no zone left
    to depend on. The result is the same for every connection that ever runs
    it.

    Dropping time_bucket costs nothing: its 1-day buckets over a timestamptz
    are epoch-aligned, and the epoch is itself a UTC midnight, so it was
    already landing on UTC day boundaries - the unqualified `::date` is the
    only thing that threw that away.
    """
    return f"({timestamp_expr} AT TIME ZONE 'UTC')::date"


# The trigger that keeps agent_event_day_rollup in step with agent_events
# (#1253). `day` comes from utc_day() above, which the heatmap's read side
# buckets with too, so the rollup's days are the heatmap's days by construction
# rather than by agreement between two pieces of code.
#
# WHY THE UPSERT HAS A `WHERE` (#1371). Without one, EVERY event after the
# first for a triple rewrote the row - `LEAST(x, x)` and `commits + 0` produce
# the values already stored, and PostgreSQL has no way to know that, so it
# writes a new tuple, the index entries that point at it, and the WAL for both.
# The predicate below is the condition under which the row would actually
# change, so an event that cannot change it now costs a conflict probe and
# nothing else. Most events are neither a commit nor the earliest of their
# triple, so most events take that path.
ROLLUP_TRIGGER_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION agent_event_day_rollup_apply() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO agent_event_day_rollup (day, session_id, execution_id, first_time, commits)
    VALUES (
        {utc_day("NEW.time")},
        NEW.session_id,
        NEW.execution_id,
        NEW.time,
        CASE WHEN NEW.event_type = '{GIT_COMMIT}' THEN 1 ELSE 0 END
    )
    ON CONFLICT ON CONSTRAINT agent_event_day_rollup_key DO UPDATE
    SET first_time = LEAST(agent_event_day_rollup.first_time, EXCLUDED.first_time),
        commits    = agent_event_day_rollup.commits + EXCLUDED.commits
    WHERE EXCLUDED.first_time < agent_event_day_rollup.first_time
       OR EXCLUDED.commits <> 0;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# Recompute every rollup row from the raw events, and RECONCILE the ones that
# are already there.
#
# This used to end `DO NOTHING`, which was enough while the only caller was a
# first startup filling an empty table. It is not enough for the other caller
# (_create_day_rollup, when the trigger turns out to have been missing or
# disabled): those rows exist and are STALE - short by exactly the events that
# arrived while nothing was maintaining them - and DO NOTHING would leave every
# one of them short.
#
# `SET ... = EXCLUDED` is safe precisely because the SELECT is a complete
# aggregate over all of agent_events, so EXCLUDED is the whole truth for the
# triple rather than a delta. That also makes this statement idempotent in the
# stronger sense the old one only approximated: re-running it converges, rather
# than merely not double-counting.
ROLLUP_BACKFILL_SQL = f"""
INSERT INTO agent_event_day_rollup (day, session_id, execution_id, first_time, commits)
SELECT
    {utc_day("time")},
    session_id,
    execution_id,
    MIN(time),
    COUNT(*) FILTER (WHERE event_type = '{GIT_COMMIT}')
FROM agent_events
GROUP BY 1, 2, 3
ON CONFLICT ON CONSTRAINT agent_event_day_rollup_key DO UPDATE
SET first_time = EXCLUDED.first_time,
    commits    = EXCLUDED.commits;
"""


def trigger_live_sql(trigger: str) -> str:
    """Is the named trigger on agent_events attached AND firing? See _rollup_is_complete()."""
    return f"""
SELECT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgrelid = to_regclass('agent_events')
      AND tgname = '{trigger}'
      -- Only 'O' (origin) and 'A' (always) fire for the ordinary, origin-mode
      -- inserts the application makes. 'D' is disabled, and 'R' (ENABLE REPLICA
      -- TRIGGER) fires only under session_replication_role = replica - so both
      -- leave events uncounted and must earn a reconcile (#1371, review r2).
      AND tgenabled IN ('O', 'A')
)
"""


# Is the rollup still being maintained? See _rollup_is_complete().
ROLLUP_TRIGGER_LIVE_SQL = trigger_live_sql("agent_events_day_rollup")

# One stable key for the whole rollup schema step (#1371). Derived from a name
# the way PostgresImportLedger derives its keys, rather than picked as a magic
# number, so it cannot collide with those by accident and a row in `pg_locks`
# can be traced back to this line.
ROLLUP_SCHEMA_LOCK_KEY: int = struct.unpack(
    ">q", hashlib.blake2b(b"agent_event_day_rollup:schema", digest_size=8).digest()
)[0]


# TAKE agent_events FIRST. Re-attaching a rollup trigger means DROP TRIGGER
# (ACCESS EXCLUSIVE) and CREATE TRIGGER (SHARE ROW EXCLUSIVE) on a hypertable,
# and TimescaleDB applies both to every chunk as well as to the parent. It
# locks the chunks BEFORE the parent, while a concurrent COPY holds the parent
# and then asks for the chunk it writes to: a lock-order deadlock, measured on
# timescaledb 2.29.2 with a writer running through startup (#1558 review r2).
# PostgreSQL aborts one side - either an ingest write or this startup.
# Locking the parent explicitly first, which LOCK TABLE does before it
# recurses into the chunks, puts both sides in the same order. It costs
# nothing new: DROP TRIGGER takes this lock anyway, for the same milliseconds.
AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL = "LOCK TABLE agent_events IN ACCESS EXCLUSIVE MODE"


# THE USAGE ROLLUP (E1, "pages load fast and stay fast").
#
# /metrics and the heatmap's usage totals read canonical usage, and canonical
# usage read raw agent_events: every session_summary and token_usage row, out
# of compressed chunks segmented by session_id, JSONB parsed per row, on every
# request. These two tables hold the same rows already extracted - summaries
# one for one, turns summed per (session, execution, model) - so the reads
# grow with sessions rather than with turns. The meaning of the columns is
# canonical_usage's (summary_usage_columns / turn_usage_columns), imported
# rather than restated, so a change to what a row contributes reaches the
# rollup and the raw read together.
#
# Same shape as agent_event_day_rollup, and for the same reasons: a trigger
# sees COPY, which insert_batch uses and no application hook does; and it is
# not a projection, so it never replays the event store (#1318). It is a NEW
# object rather than a VERSION bump on anything existing, so a deploy pays one
# backfill over the two usage event types and nothing replays.
#
# The turn key is NULLS NOT DISTINCT for the reason ROLLUP_KEY_SQL's is: a
# NULL execution_id or model must group with NULL, or the rollup grows a row
# per turn and loses the bound it exists for.
#
# WHO WROTE A ROW, AND WHY IT MATTERS: THE NON-BLOCKING BACKFILL (#1558 r2).
#
# Every row says whether the TRIGGER wrote it (`backfilled = FALSE`) or the
# BACKFILL did (`backfilled = TRUE`), and the two never touch each other's
# rows. That separation is what lets the backfill run without holding
# agent_events against inserts:
#
#   * The trigger writes a row in the same transaction as the event that
#     fired it. So in ANY snapshot, a post-trigger event and its trigger
#     contribution are either both visible or both invisible.
#   * The backfill therefore writes, per key, (every event in its snapshot)
#     MINUS (every trigger contribution in that same snapshot), as ONE
#     statement, so one snapshot. What is left is exactly the events the
#     trigger never saw: those committed before it existed, or while it was
#     disabled. Events committed during the backfill are the trigger's alone.
#   * It REPLACES its own rows (delete, then insert the difference), so a
#     re-run, a resume after a crash, or a second replica converges on the
#     same numbers instead of adding to them.
#
# Summaries have no natural key, so "minus" is the multiset EXCEPT ALL over
# every stored column. Turns are summed, so the turn row carries
# `observations`, the number of token_usage events it sums, and the backfill
# keeps a key only where the events outnumber the trigger's observations -
# a key with no pre-trigger turns gets no backfilled row, as it would have
# had no row in a raw read either.
USAGE_ROLLUP_TABLES_SQL = (
    f"""
    CREATE TABLE IF NOT EXISTS {SUMMARY_USAGE_TABLE} (
        session_id            TEXT        NOT NULL,
        execution_id          TEXT,
        time                  TIMESTAMPTZ NOT NULL,
        model                 TEXT,
        requested_model       TEXT,
        has_requested_model   BOOLEAN     NOT NULL,
        vendor_cost_usd       NUMERIC,
        input_tokens          BIGINT      NOT NULL,
        output_tokens         BIGINT      NOT NULL,
        cache_creation_tokens BIGINT      NOT NULL,
        cache_read_tokens     BIGINT      NOT NULL,
        backfilled            BOOLEAN     NOT NULL DEFAULT FALSE
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_{SUMMARY_USAGE_TABLE}_session
    ON {SUMMARY_USAGE_TABLE} (session_id)
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_{SUMMARY_USAGE_TABLE}_execution
    ON {SUMMARY_USAGE_TABLE} (execution_id)
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {TURN_USAGE_ROLLUP_TABLE} (
        session_id            TEXT    NOT NULL,
        execution_id          TEXT,
        model                 TEXT,
        requested_model       TEXT,
        has_requested_model   BOOLEAN NOT NULL,
        input_tokens          BIGINT  NOT NULL,
        output_tokens         BIGINT  NOT NULL,
        cache_creation_tokens BIGINT  NOT NULL,
        cache_read_tokens     BIGINT  NOT NULL,
        observations          BIGINT  NOT NULL,
        backfilled            BOOLEAN NOT NULL DEFAULT FALSE,
        CONSTRAINT {TURN_USAGE_ROLLUP_TABLE}_key UNIQUE NULLS NOT DISTINCT
            (session_id, execution_id, model, requested_model, has_requested_model, backfilled)
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_{TURN_USAGE_ROLLUP_TABLE}_execution
    ON {TURN_USAGE_ROLLUP_TABLE} (execution_id)
    """,
    # The heatmap's member-session read is ANY over many sessions; this one
    # serves it, since the key's leading column alone is not a usable index
    # for every planner choice.
    f"""
    CREATE INDEX IF NOT EXISTS idx_{TURN_USAGE_ROLLUP_TABLE}_session
    ON {TURN_USAGE_ROLLUP_TABLE} (session_id)
    """,
    # One row once a backfill has finished with the trigger live. Absent means
    # "not known complete": startup backfills, and validate() refuses to serve.
    f"""
    CREATE TABLE IF NOT EXISTS {USAGE_ROLLUP_STATE_TABLE} (
        singleton     BOOLEAN     PRIMARY KEY DEFAULT TRUE CHECK (singleton),
        backfilled_at TIMESTAMPTZ NOT NULL
    )
    """,
)

_SUMMARY_COLUMNS = (
    "session_id, execution_id, time, model, requested_model, has_requested_model, "
    "vendor_cost_usd, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens"
)
_TURN_KEY_COLUMNS = "session_id, execution_id, model, requested_model, has_requested_model"
_TURN_COLUMNS = (
    f"{_TURN_KEY_COLUMNS}, "
    "input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, observations"
)

USAGE_ROLLUP_TRIGGER_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION agent_usage_rollup_apply() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_type = '{SESSION_SUMMARY}' THEN
        INSERT INTO {SUMMARY_USAGE_TABLE} ({_SUMMARY_COLUMNS})
        SELECT NEW.session_id, NEW.execution_id, NEW.time,
            {summary_usage_columns("NEW.data")};
    ELSIF NEW.event_type = '{TOKEN_USAGE}' THEN
        INSERT INTO {TURN_USAGE_ROLLUP_TABLE} ({_TURN_COLUMNS})
        SELECT NEW.session_id, NEW.execution_id,
            {recorded_model_select("NEW.data")},
            {turn_usage_columns("NEW.data")},
            1 AS observations
        ON CONFLICT ON CONSTRAINT {TURN_USAGE_ROLLUP_TABLE}_key DO UPDATE
        SET input_tokens = {TURN_USAGE_ROLLUP_TABLE}.input_tokens + EXCLUDED.input_tokens,
            output_tokens = {TURN_USAGE_ROLLUP_TABLE}.output_tokens + EXCLUDED.output_tokens,
            cache_creation_tokens =
                {TURN_USAGE_ROLLUP_TABLE}.cache_creation_tokens + EXCLUDED.cache_creation_tokens,
            cache_read_tokens =
                {TURN_USAGE_ROLLUP_TABLE}.cache_read_tokens + EXCLUDED.cache_read_tokens,
            observations = {TURN_USAGE_ROLLUP_TABLE}.observations + 1;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# The sessions the backfill visits, in batches. Read from the day rollup,
# which has a row for every session that emitted ANY event and is reconciled
# by _create_day_rollup() immediately before this runs (005 is a prerequisite
# of 007 by hand, and validate() requires both), so it lists every session
# that could hold a usage event the trigger missed, without a scan of
# agent_events. A session first seen after this read has no event the trigger
# missed, so it needs no visit.
USAGE_ROLLUP_BACKFILL_SESSIONS_SQL = """
SELECT DISTINCT session_id
FROM agent_event_day_rollup
ORDER BY session_id
"""


def usage_rollup_backfill_sql(sessions: str) -> tuple[str, ...]:
    """Replace the backfilled rows for ``sessions`` with what the trigger missed.

    ``sessions`` narrows agent_events and the rollup identically: a
    ``session_id = ANY($1)`` batch at startup, or ``TRUE`` in the hand-applied
    migration. Each INSERT reads the events and the trigger's rows in ONE
    statement, so one snapshot - the guarantee the subtraction rests on (see
    the comment above USAGE_ROLLUP_TABLES_SQL).
    """
    return (
        f"DELETE FROM {SUMMARY_USAGE_TABLE} WHERE backfilled AND {sessions}",
        f"DELETE FROM {TURN_USAGE_ROLLUP_TABLE} WHERE backfilled AND {sessions}",
        f"""
    INSERT INTO {SUMMARY_USAGE_TABLE} ({_SUMMARY_COLUMNS}, backfilled)
    SELECT {_SUMMARY_COLUMNS}, TRUE
    FROM (
        SELECT session_id, execution_id, time, {summary_usage_columns()}
        FROM agent_events
        WHERE event_type = '{SESSION_SUMMARY}' AND {sessions}
        EXCEPT ALL
        SELECT {_SUMMARY_COLUMNS}
        FROM {SUMMARY_USAGE_TABLE}
        WHERE NOT backfilled AND {sessions}
    ) missed
    """,
        f"""
    INSERT INTO {TURN_USAGE_ROLLUP_TABLE} ({_TURN_COLUMNS}, backfilled)
    SELECT e.session_id, e.execution_id, e.model, e.requested_model, e.has_requested_model,
        e.input_tokens - COALESCE(t.input_tokens, 0),
        e.output_tokens - COALESCE(t.output_tokens, 0),
        e.cache_creation_tokens - COALESCE(t.cache_creation_tokens, 0),
        e.cache_read_tokens - COALESCE(t.cache_read_tokens, 0),
        e.observations - COALESCE(t.observations, 0),
        TRUE
    FROM (
        SELECT session_id, execution_id, {recorded_model_select()},
            SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
            SUM(cache_creation_tokens) AS cache_creation_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            COUNT(*) AS observations
        FROM (
            SELECT session_id, execution_id, data, {turn_usage_columns()}
            FROM agent_events
            WHERE event_type = '{TOKEN_USAGE}' AND {sessions}
        ) turns
        GROUP BY session_id, execution_id, {recorded_model_group_by()}
    ) e
    LEFT JOIN {TURN_USAGE_ROLLUP_TABLE} t
      ON NOT t.backfilled
     AND t.session_id = e.session_id
     AND t.execution_id IS NOT DISTINCT FROM e.execution_id
     AND t.model IS NOT DISTINCT FROM e.model
     AND t.requested_model IS NOT DISTINCT FROM e.requested_model
     AND t.has_requested_model = e.has_requested_model
    WHERE e.observations > COALESCE(t.observations, 0)
    """,
    )


# Startup: one batch of sessions per transaction, bound as $1.
USAGE_ROLLUP_BACKFILL_SQL = usage_rollup_backfill_sql("session_id = ANY($1::text[])")
# The hand-applied migration: every session, still one snapshot per INSERT.
USAGE_ROLLUP_BACKFILL_ALL_SQL = usage_rollup_backfill_sql("TRUE")
USAGE_ROLLUP_BACKFILL_BATCH_SESSIONS = 500

USAGE_ROLLUP_MARK_COMPLETE_SQL = f"""
INSERT INTO {USAGE_ROLLUP_STATE_TABLE} (singleton, backfilled_at) VALUES (TRUE, now())
ON CONFLICT (singleton) DO UPDATE SET backfilled_at = EXCLUDED.backfilled_at
"""
USAGE_ROLLUP_MARK_INCOMPLETE_SQL = f"DELETE FROM {USAGE_ROLLUP_STATE_TABLE}"
USAGE_ROLLUP_IS_MARKED_COMPLETE_SQL = f"SELECT EXISTS (SELECT 1 FROM {USAGE_ROLLUP_STATE_TABLE})"

USAGE_ROLLUP_SCHEMA_LOCK_KEY: int = struct.unpack(
    ">q", hashlib.blake2b(b"agent_usage_rollup:schema", digest_size=8).digest()
)[0]

USAGE_ROLLUP_TRIGGER = "agent_events_usage_rollup"


_DAY_ROLLUP_MIGRATION = "projection_stores/migrations/005_agent_event_day_rollup.sql"
_USAGE_ROLLUP_MIGRATION = "projection_stores/migrations/007_agent_usage_rollup.sql"

# What validate() requires beyond agent_events' columns, and the hand-applied
# migration that creates each when auto-create is off.
_ROLLUP_TABLES: tuple[tuple[str, str], ...] = (
    ("agent_event_day_rollup", _DAY_ROLLUP_MIGRATION),
    (SUMMARY_USAGE_TABLE, _USAGE_ROLLUP_MIGRATION),
    (TURN_USAGE_ROLLUP_TABLE, _USAGE_ROLLUP_MIGRATION),
    (USAGE_ROLLUP_STATE_TABLE, _USAGE_ROLLUP_MIGRATION),
)
_ROLLUP_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("agent_events_day_rollup", _DAY_ROLLUP_MIGRATION),
    (USAGE_ROLLUP_TRIGGER, _USAGE_ROLLUP_MIGRATION),
)


class SchemaValidationError(Exception):
    """Raised when database schema doesn't match expected schema."""

    pass


# E2: see EventStoreSchema._create_rollup_execution_index and
# migrations/008_day_rollup_execution_index.sql, which applies the same index.
ROLLUP_EXECUTION_INDEX_SQL = """
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rollup_execution_day
    ON agent_event_day_rollup (execution_id, day)
"""

# NULL when the index does not exist, else whether it is usable.
ROLLUP_EXECUTION_INDEX_VALID_SQL = """
SELECT i.indisvalid
FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid
WHERE c.relname = 'idx_rollup_execution_day'
  AND c.relnamespace = current_schema()::regnamespace
"""


class EventStoreSchema:
    """Manages the agent_events table schema.

    Handles DDL creation, TimescaleDB hypertable setup, index creation,
    compression policies, and schema validation.

    Schema Management Strategy:
        THIS CLASS IS THE AUTHORITATIVE SCHEMA. ensure_schema() runs at every
        API startup and is the only thing that creates these objects, in
        production and in test alike.

        The files under projection_stores/migrations/ are NOT executed. No
        migration runner exists in this repository for that directory - the
        one `just` target that feeds .sql to psql is `feedback-migrate`, which
        points at lib/ui-feedback. They are design documents that describe
        what this code does, and they are only as true as the last person to
        edit both. Do not deploy on the belief that one of them ran.

        (This docstring used to say the opposite - "the migration file is
        authoritative", "In production: Run migrations before deploying" -
        and it was never true of this repository. Corrected under #1253.)

        Because the SQL files are documentation, they cannot drift silently
        into production, but they can still mislead a reader. So when changing
        schema:
        1. Change it HERE - that is the change that ships
        2. Update the matching migration file so the description stays true
        3. Run test_schema_consistency.py to verify Python matches SQL
        4. Update EXPECTED_COLUMNS in models.py to match
        5. Update docker/init-db if needed for fresh containers

        The drift tests in tests/events/ exist to stop the two separating, and
        since #1338 they cover indexes as well as columns.

        Auto-creation is disabled when skip_auto_create=True, which turns
        agent_events DDL off entirely with no replacement. That is correct for
        a database whose schema is managed out of band, and a guarantee of an
        empty schema for one that is not.
    """

    def __init__(self, *, skip_auto_create: bool = False) -> None:
        self._skip_auto_create = skip_auto_create

    @property
    def skip_auto_create(self) -> bool:
        """Does this deployment apply its own DDL?

        Public because it is not this class's private business: it is the
        deployment's policy, and every table the store readies has to honour
        the same answer. ``AgentEventStore.initialize`` passes it on to
        ``tool_call_counts.ensure_ready``, which owns a table this class does
        not - reading ``_skip_auto_create`` through the underscore instead
        would make one policy look like two.
        """
        return self._skip_auto_create

    async def ensure_schema(self, conn: asyncpg.Connection) -> None:
        """Create schema if needed and validate it.

        Args:
            conn: Active database connection
        """
        # Enable TimescaleDB extension (always needed)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

        if not self._skip_auto_create:
            await self._create_table(conn)
            await self._create_indexes(conn)
            await self._configure_compression(conn)
            await self._create_day_rollup(conn)
            await self._create_rollup_execution_index(conn)
            await self._create_usage_rollup(conn)

        await self.validate(conn)

    async def _create_table(self, conn: asyncpg.Connection) -> None:
        """Create agent_events table and hypertable.

        Schema MUST match: projection_stores/migrations/002_agent_events.sql,
        which documents this DDL but does not run - see the class docstring.
        """
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_events (
                time TIMESTAMPTZ NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                execution_id TEXT,
                phase_id TEXT,
                data JSONB NOT NULL
            )
        """)

        # Create hypertable (partitioned by time)
        await conn.execute("""
            SELECT create_hypertable(
                'agent_events',
                'time',
                if_not_exists => TRUE,
                chunk_time_interval => INTERVAL '1 day'
            )
        """)

    async def _create_indexes(self, conn: asyncpg.Connection) -> None:
        """Create indexes for common queries.

        Index set MUST match: projection_stores/migrations/002_agent_events.sql,
        which carries the reasoning for each one. Nothing applies that migration
        (see the class docstring), so this method is the only path by which any
        of these indexes reaches a database - a new index added only to the .sql
        file is a no-op everywhere.

        Pinned by test_agent_events_index_set_reaches_a_fresh_install.py.
        """
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_session
            ON agent_events (session_id, time DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_execution
            ON agent_events (execution_id, time DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type
            ON agent_events (event_type, time DESC)
        """)

        # The cost read paths pair an id with an event_type; the three indexes
        # above all lead on one column and then on `time`, so none of them
        # serves that pair (#1338). Uncompressed chunks only - see the migration.
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_session_type
            ON agent_events (session_id, event_type, time DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_execution_type
            ON agent_events (execution_id, event_type, time DESC)
        """)

        # `idx_events_data`, a GIN index over every event's whole `data`
        # payload, is DELIBERATELY NOT CREATED HERE, and is not declared in
        # 002_agent_events.sql either, so the two stay in agreement.
        #
        # It was declared in that migration and never created, which the index
        # test found as drift on its first run. Resolving that drift by
        # creating it would have been the wrong direction: nothing in this
        # repository queries `data` by containment, so the index earns nothing
        # - and it is not free. `_create_indexes` runs inside API STARTUP, and
        # a plain `CREATE INDEX` (not CONCURRENTLY, which cannot run in this
        # transaction) takes a lock that holds writes off `agent_events` for
        # as long as the build takes. On an install with real history that is
        # the observability write path stalled at boot, once, with no warning
        # and nothing gained.
        #
        # So the drift is resolved by removing the declaration rather than by
        # honouring it. If a query that needs it ever arrives, it comes back
        # with that query, built CONCURRENTLY outside startup.

    async def _create_day_rollup(self, conn: asyncpg.Connection) -> None:
        """Create the per-day rollup that bounds the contribution heatmap (#1253).

        This code IS the schema. The matching file,
        projection_stores/migrations/005_agent_event_day_rollup.sql, documents
        it and explains it at length, but nothing executes that file - see the
        class docstring.

        THE BACKFILL IS SKIPPED ONLY WHEN THE ROLLUP IS KNOWN COMPLETE.
        ensure_schema() runs at EVERY API startup, so anything unconditional
        here is paid on every restart. The backfill is a GROUP BY over ALL of
        agent_events - it decompresses every chunk, and it grows with the data
        - held inside a transaction that has taken SHARE ROW EXCLUSIVE on
        agent_events for the CREATE TRIGGER. Unconditionally, that blocks all
        event ingestion for the length of a full scan, every restart, forever.
        It never CORRUPTED anything, it just cost a full outage-shaped scan to
        achieve nothing.

        So the backfill is gated - on `_rollup_is_complete()`, which asks both
        halves of the question rather than only the cheap one. The single
        transaction below is what makes that gate sound rather than merely
        cheap:

          - if this transaction commits, the table exists AND the backfill
            that ran inside it committed with it;
          - if it aborts at any point, CREATE TABLE rolls back too, so the
            table does NOT exist and the next startup redoes the whole thing.

        There is no third state, so a half-populated rollup is not reachable
        by that route. It IS reachable by the other one - a trigger dropped or
        disabled out from under a table that stays - which is why the gate
        does not stop at the table. See `_rollup_is_complete()`.

        Everything else here is re-run every startup and is O(1): CREATE ...
        IF NOT EXISTS resolves to a catalogue lookup, ROLLUP_KEY_SQL to one
        more (it returns without touching the table once the key is the one it
        wants - see its comment), and CREATE OR REPLACE FUNCTION rewrites one
        pg_proc row. Re-attaching the trigger still takes SHARE ROW EXCLUSIVE
        (PostgreSQL's CREATE TRIGGER takes ShareRowExclusiveLock, not
        ACCESS EXCLUSIVE as this used to claim - it still conflicts with
        INSERT, which is the property everything here relies on), so ingestion
        still pauses for it, but it pauses for a catalogue write rather than
        for a scan. It is re-attached rather than skipped so that a change to
        the trigger's definition - which rows it fires on, which function it
        calls - reaches a database that already has the old one.

        CONCURRENT FIRST STARTUPS pay the backfill at most once, because of
        the advisory lock taken below. Without it two replicas could both read
        "no rollup" before either had committed a CREATE TABLE, and both would
        then scan the whole of agent_events - each one an ingestion outage, for
        a result the other had already produced.
        """
        async with conn.transaction():
            # Held for the rest of the transaction, and taken BEFORE anything
            # is read, so two replicas starting together queue here instead of
            # racing: the loser wakes up after the winner has committed and
            # sees a finished rollup.
            await conn.execute("SELECT pg_advisory_xact_lock($1)", ROLLUP_SCHEMA_LOCK_KEY)
            await conn.execute(AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL)
            # Read inside the transaction, so it is the same snapshot the DDL
            # below writes into - and before the DROP TRIGGER further down,
            # which would otherwise make every startup look like a broken one.
            rollup_is_complete = await self._rollup_is_complete(conn)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_event_day_rollup (
                    day          DATE        NOT NULL,
                    session_id   TEXT        NOT NULL,
                    execution_id TEXT,
                    first_time   TIMESTAMPTZ NOT NULL,
                    commits      BIGINT      NOT NULL DEFAULT 0
                )
            """)
            await conn.execute(ROLLUP_KEY_SQL)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rollup_session_day
                ON agent_event_day_rollup (session_id, day)
            """)
            await conn.execute(ROLLUP_TRIGGER_FUNCTION_SQL)
            await conn.execute("""
                DROP TRIGGER IF EXISTS agent_events_day_rollup ON agent_events
            """)
            await conn.execute("""
                CREATE TRIGGER agent_events_day_rollup
                AFTER INSERT ON agent_events
                FOR EACH ROW EXECUTE FUNCTION agent_event_day_rollup_apply()
            """)
            if not rollup_is_complete:
                await conn.execute(ROLLUP_BACKFILL_SQL)

    async def _create_rollup_execution_index(self, conn: asyncpg.Connection) -> None:
        """Index the day rollup by execution, without ever pausing ingestion (E2).

        The execution-keyed half of syn_domain.agent_event_span: which days an
        execution has telemetry on, so its hypertable reads can be bounded.

        CONCURRENTLY and outside any transaction - deliberately NOT inside
        _create_day_rollup's, which holds the agent_events trigger lock and
        would make every insert wait for the build. The trigger writes this
        table on every insert, so a plain CREATE INDEX would block it too.

        A concurrent build that died leaves an INVALID index that IF NOT EXISTS
        would then skip forever, so an invalid one is dropped and rebuilt. Any
        failure is logged and swallowed: the index only makes the span lookup
        fast; without it the lookup scans the rollup and returns the same span.
        """
        try:
            valid = await conn.fetchval(ROLLUP_EXECUTION_INDEX_VALID_SQL)
            if valid is True:
                return
            if valid is False:
                await conn.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_rollup_execution_day")
            await conn.execute(ROLLUP_EXECUTION_INDEX_SQL)
        except asyncpg.PostgresError:
            logger.warning(
                "Could not build idx_rollup_execution_day; execution span lookups "
                "will scan agent_event_day_rollup until the next startup",
                exc_info=True,
            )

    async def _create_usage_rollup(self, conn: asyncpg.Connection) -> None:
        """Create the usage rollup that bounds /metrics and the heatmap (E1).

        TWO PHASES, AND ONLY THE FIRST LOCKS INGEST (#1558 review r2). The
        first transaction creates the tables and (re)creates the trigger,
        holding agent_events (AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL, taken first
        to keep the lock order deadlock-free), so inserts wait for it - but
        it does no scan: milliseconds. If the rollup is not
        known complete it also clears the completion mark in that same
        transaction, so no later reader can mistake a half-done backfill for
        a finished one.

        The backfill then runs in batches of sessions, one short transaction
        each, holding no lock an insert waits on: see the comment above
        USAGE_ROLLUP_TABLES_SQL for why the trigger's rows and the backfill's
        rows add up to every event exactly once while ingest carries on. It
        runs only when the rollup is not known complete - tables present, the
        trigger live, AND the mark present - so a restart pays catalogue
        lookups, a backfill interrupted by a crash resumes on the next start,
        and a trigger found dropped or disabled earns a full reconcile.
        """
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", USAGE_ROLLUP_SCHEMA_LOCK_KEY)
            await conn.execute(AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL)
            tables_exist = [
                (await conn.fetchval(f"SELECT to_regclass('{table}') IS NOT NULL")) is True
                for table in (
                    SUMMARY_USAGE_TABLE,
                    TURN_USAGE_ROLLUP_TABLE,
                    USAGE_ROLLUP_STATE_TABLE,
                )
            ]
            trigger_is_live: bool = (
                await conn.fetchval(trigger_live_sql(USAGE_ROLLUP_TRIGGER))
            ) is True
            marked_complete = all(tables_exist) and (
                (await conn.fetchval(USAGE_ROLLUP_IS_MARKED_COMPLETE_SQL)) is True
            )
            for ddl in USAGE_ROLLUP_TABLES_SQL:
                await conn.execute(ddl)
            await conn.execute(USAGE_ROLLUP_TRIGGER_FUNCTION_SQL)
            await conn.execute(f"DROP TRIGGER IF EXISTS {USAGE_ROLLUP_TRIGGER} ON agent_events")
            await conn.execute(f"""
                CREATE TRIGGER {USAGE_ROLLUP_TRIGGER}
                AFTER INSERT ON agent_events
                FOR EACH ROW EXECUTE FUNCTION agent_usage_rollup_apply()
            """)
            needs_backfill = not (trigger_is_live and marked_complete)
            if needs_backfill:
                await conn.execute(USAGE_ROLLUP_MARK_INCOMPLETE_SQL)
        if needs_backfill:
            await self.backfill_usage_rollup(conn)

    @staticmethod
    async def backfill_usage_rollup(
        conn: asyncpg.Connection, *, batch_sessions: int | None = None
    ) -> None:
        """Fill the usage rollup with every event its trigger did not see.

        Requires the trigger to exist already. Never blocks an insert into
        agent_events; idempotent, so safe to re-run or to run from two
        replicas at once (the batches serialise on the schema lock).
        """
        size = batch_sessions or USAGE_ROLLUP_BACKFILL_BATCH_SESSIONS
        sessions = [
            str(r["session_id"]) for r in await conn.fetch(USAGE_ROLLUP_BACKFILL_SESSIONS_SQL)
        ]
        for start in range(0, len(sessions), size):
            batch = sessions[start : start + size]
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", USAGE_ROLLUP_SCHEMA_LOCK_KEY)
                for statement in USAGE_ROLLUP_BACKFILL_SQL:
                    await conn.execute(statement, batch)
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", USAGE_ROLLUP_SCHEMA_LOCK_KEY)
            await conn.execute(USAGE_ROLLUP_MARK_COMPLETE_SQL)

    async def _rollup_is_complete(self, conn: asyncpg.Connection) -> bool:
        """Whether the rollup can be trusted to already hold every event.

        The table existing used to be the whole answer, and it is only half of
        one (#1371). The rollup is maintained by a trigger, and a trigger can
        be dropped or disabled without the table going anywhere - by a manual
        `ALTER TABLE ... DISABLE TRIGGER` during an incident, by a restore, by
        a test. Every event that arrives while it is gone is missing from the
        rollup, and the caller re-attaches the trigger unconditionally, so on
        the old gate the gap would never close: the heatmap would under-report
        that window forever, with nothing anywhere saying so.

        So completeness is "the table is there AND something is keeping it
        up to date", and a no to either sends the caller to the reconciling
        backfill. That backfill recomputes rather than fills gaps, so it
        repairs a short row as readily as it creates a missing one.

        Both halves are asked as a definite boolean and compared against True,
        so anything else - including the None asyncpg hands back from an empty
        result - falls to the safe side and backfills. That costs one redundant
        scan; the other spelling would skip a backfill that never happened.
        """
        rollup_exists: bool = (
            await conn.fetchval("SELECT to_regclass('agent_event_day_rollup') IS NOT NULL")
        ) is True
        trigger_is_live: bool = (await conn.fetchval(ROLLUP_TRIGGER_LIVE_SQL)) is True
        return rollup_exists and trigger_is_live

    async def _configure_compression(self, conn: asyncpg.Connection) -> None:
        """Configure TimescaleDB compression policies."""
        try:
            await conn.execute("""
                ALTER TABLE agent_events SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'session_id',
                    timescaledb.compress_orderby = 'time DESC'
                )
            """)

            await conn.execute("""
                SELECT add_compression_policy(
                    'agent_events',
                    INTERVAL '1 day',
                    if_not_exists => TRUE
                )
            """)
        except asyncpg.PostgresError:
            # Compression might already be enabled
            pass

    async def validate(self, conn: asyncpg.Connection) -> None:
        """Validate that database schema matches expected columns.

        Raises:
            SchemaValidationError: If schema doesn't match
        """
        rows = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'agent_events'
            AND table_schema = 'public'
        """)

        actual_schema = {row["column_name"]: row["data_type"] for row in rows}

        mismatches = []
        for col, expected_type in EXPECTED_COLUMNS.items():
            actual_type = actual_schema.get(col)
            if actual_type is None:
                mismatches.append(f"Missing column: {col}")
            elif not actual_type.startswith(expected_type.split()[0]):
                # Partial match (e.g., "character varying" matches "character varying(100)")
                mismatches.append(f"Column {col}: expected '{expected_type}', got '{actual_type}'")

        mismatches.extend(await self._missing_rollup_objects(conn))

        if mismatches:
            msg = "Schema validation failed:\n  " + "\n  ".join(mismatches)
            logger.error(msg)
            raise SchemaValidationError(msg)

    async def _missing_rollup_objects(self, conn: asyncpg.Connection) -> list[str]:
        """The rollups the read paths depend on, and whether each is there.

        /metrics and the contribution heatmap read these relations
        unconditionally. With auto-create on, ensure_schema() has just made
        them; with SYN_SKIP_AUTO_CREATE_TABLES=true it made nothing, and they
        exist only if the migrations were applied by hand. Not checking meant
        that deployment started cleanly and then answered 503 on every
        dashboard request. A missing trigger is checked too: the tables would
        be there and simply stop growing, which nothing else would report.
        """
        missing: list[str] = []
        for table, migration in _ROLLUP_TABLES:
            exists = await conn.fetchval(f"SELECT to_regclass('{table}') IS NOT NULL")
            if exists is not True:
                missing.append(f"Missing table: {table} (apply {migration})")
        for trigger, migration in _ROLLUP_TRIGGERS:
            if (await conn.fetchval(trigger_live_sql(trigger))) is not True:
                missing.append(f"Missing or disabled trigger: {trigger} (apply {migration})")
        # Tables and a live trigger are not enough: until the backfill has
        # finished the rollup holds only what arrived after the trigger, and
        # would serve that as the whole history.
        if (
            not any(USAGE_ROLLUP_STATE_TABLE in m for m in missing)
            and (await conn.fetchval(USAGE_ROLLUP_IS_MARKED_COMPLETE_SQL)) is not True
        ):
            missing.append(
                f"Usage rollup backfill not complete: {USAGE_ROLLUP_STATE_TABLE} is empty "
                f"(apply {_USAGE_ROLLUP_MIGRATION})"
            )
        return missing
