"""A copy of each projection document without its heavy fields, for list scans (E2).

``artifact_summaries`` stores each artifact's full body in its document. A list
page needs a handful of small fields from every artifact - to filter, tally and
order them - and Postgres cannot read ``data->>'created_at'`` out of a JSONB
value stored out of line (TOAST) without fetching and decompressing the whole
value, body included. On the E2 gate's seed (6,000 artifacts of a few KB, most
stored inline) the scan over ``data`` took 11.6ms and over ``lean`` 6.1ms; the
gap grows with body size, and a body past ~2KB compressed is what goes out of
line, which is the live shape.

So such a table carries a second column, ``lean``: the document minus the
listed heavy keys, small enough to live inline. ``scan_fields`` reads
``COALESCE(lean, data)``, which never touches ``data`` once ``lean`` is set.

HOW IT STAYS RIGHT, without any writer knowing it exists:

- A ``BEFORE INSERT OR UPDATE`` trigger recomputes ``lean`` from ``data`` on
  every write, so every path that writes the table - ``save``, ``save_if``, a
  projection rebuild's re-inserts - keeps it in step in the same statement.
- Rows written before the trigger existed are backfilled in small batches,
  each its own short transaction holding only those rows' locks, so a writer
  never waits on more than one batch.
- Until a row is backfilled, ``COALESCE`` reads it from ``data``: slower,
  never wrong. That is also the whole story if the DDL could not run (a lock
  it could not get in time): ``scan_fields`` falls back to ``data`` for the
  process and the next start tries again.

NOT A PROJECTION VERSION BUMP. Nothing replays: the column is derived from the
document already stored, by the database, in place.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

#: Projection -> the document keys a list scan never needs and that make the
#: document too big to read cheaply. Add a projection here only for a field
#: that is large; the column costs a second copy of the rest of the document.
HEAVY_FIELDS: dict[str, tuple[str, ...]] = {
    "artifact_summaries": ("content",),
}

LEAN_COLUMN = "lean"

_BACKFILL_BATCH = 200

#: Long enough for a busy table, short enough that a writer queued behind the
#: ALTER never waits long: a lock request blocks everything queued after it.
_DDL_LOCK_TIMEOUT = "2s"


def _heavy_array(projection: str) -> str:
    keys = ", ".join(f"'{key}'" for key in HEAVY_FIELDS[projection])
    return f"ARRAY[{keys}]::text[]"


def lean_source(*, lean_ready: bool) -> str:
    """The SQL expression a list scan reads a document from."""
    return f"COALESCE({LEAN_COLUMN}, data)" if lean_ready else "data"


async def ensure_lean_column(pool: asyncpg.Pool, projection: str, table_name: str) -> bool:
    """Create the lean column and its trigger if missing, then backfill. True if usable."""
    if projection not in HEAVY_FIELDS:
        return False
    function = f"{table_name}_lean_apply"
    trigger = f"{table_name}_lean"
    try:
        async with pool.acquire() as conn:
            # Catalogue reads first, so a restart that finds everything in
            # place takes no table lock at all.
            has_column = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = $1 "
                "AND column_name = $2)",
                table_name,
                LEAN_COLUMN,
            )
            has_trigger = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                "WHERE tgrelid = $1::regclass AND tgname = $2 AND tgenabled <> 'D')",
                table_name,
                trigger,
            )
            if not (has_column and has_trigger):
                async with conn.transaction():
                    await conn.execute(f"SET LOCAL lock_timeout = '{_DDL_LOCK_TIMEOUT}'")
                    # Metadata only: a nullable column with no default
                    # rewrites nothing, so the exclusive lock is held for a
                    # catalogue write.
                    await conn.execute(
                        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {LEAN_COLUMN} JSONB"
                    )
                    await conn.execute(f"""
                        CREATE OR REPLACE FUNCTION {function}() RETURNS TRIGGER AS $$
                        BEGIN
                            NEW.{LEAN_COLUMN} := NEW.data - {_heavy_array(projection)};
                            RETURN NEW;
                        END;
                        $$ LANGUAGE plpgsql
                    """)
                    await conn.execute(f"""
                        CREATE OR REPLACE TRIGGER {trigger}
                        BEFORE INSERT OR UPDATE ON {table_name}
                        FOR EACH ROW EXECUTE FUNCTION {function}()
                    """)
            await _backfill(conn, projection, table_name)
    except Exception:
        logger.warning(
            "Lean column for %s unavailable; list scans read whole documents",
            table_name,
            exc_info=True,
        )
        return False
    return True


async def _backfill(
    conn: asyncpg.pool.PoolConnectionProxy, projection: str, table_name: str
) -> None:
    """Fill ``lean`` for rows written before the trigger, a batch per transaction."""
    while True:
        status = await conn.execute(f"""
            UPDATE {table_name} SET {LEAN_COLUMN} = data - {_heavy_array(projection)}
            WHERE id IN (
                SELECT id FROM {table_name} WHERE {LEAN_COLUMN} IS NULL
                LIMIT {_BACKFILL_BATCH}
                FOR UPDATE SKIP LOCKED
            )
        """)
        if int(status.split()[-1]) == 0:
            return
