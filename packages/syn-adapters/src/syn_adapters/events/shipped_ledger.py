"""The shipped ledger in TimescaleDB, beside ``agent_events`` (Lane 2).

Implements ``ShippedLedger`` (``orchestration._shared.shipped_ledger``). See
that module for the semantics; this one is how they hold in SQL.

FACTS AND THE DERIVED ROLLUP ARE SEPARATE, AND ONLY THE ROLLUP IS EVER RESET.

- Fact tables: ``shipped_commits``, ``shipped_pull_requests``,
  ``github_pull_request_merges`` and ``github_repository_aliases``. They are
  the record. Merges have no other source and history keeps only previews, so
  nothing here truncates or drops them; their shape changes only through the
  numbered, forward-only migrations below.
- ``shipped_daily`` is a pure function of the facts. Every write recomputes
  the rollup rows for the keys it touched FROM the facts (never by +1), so
  the rollup always equals a full rebuild; a ``ROLLUP_VERSION`` change rebuilds
  it whole from the facts.

ONE WRITER AT A TIME. Every write takes one transaction-scoped advisory lock,
so the read-decide-write of a fact and the recompute of its rollup keys cannot
interleave with another write. Write volume is commits and PRs, not
telemetry, so one lock costs nothing that matters.

ATTRIBUTION IS A RULE, NOT AN ARRIVAL ORDER. A commit sha or a PR claimed by
two observations belongs to the earliest (``observed_at`` / ``created_at``),
ties broken by the smaller execution id. A later-arriving earlier claim moves
the fact and recomputes both owners' rows.

RENAMES AND TRANSFERS. GitHub reports a merge under the repository's slug at
merge time and its stable id. ``github_repository_aliases`` records every
(slug, id) the pipeline has seen, so a PR opened under an old slug matches a
merge reported under the new one when the old slug was ever seen with that
id (the PR's own ``opened`` webhook carries it). Without that sighting the
slug alone is matched.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import ShippedDayRow, repository_key, utc_day

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    import asyncpg

    from syn_domain.contexts.orchestration import (
        CommitShipped,
        PullRequestMerged,
        PullRequestOpened,
    )

logger = logging.getLogger(__name__)

type _Conn = asyncpg.Connection | asyncpg.pool.PoolConnectionProxy
type RollupKey = tuple[date, str, str]

# =============================================================================
# Schema: forward-only migrations. NEVER edit a step once released; add one.
# Mirrored for operators in projection_stores/migrations/010_shipped_ledger.sql.
# =============================================================================

_META = """
CREATE TABLE IF NOT EXISTS shipped_ledger_meta (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    schema_version INT NOT NULL DEFAULT 0,
    rollup_version INT NOT NULL DEFAULT 0,
    backfill_version INT NOT NULL DEFAULT 0,
    backfill_cursor TEXT,
    backfill_sessions_walked BOOLEAN NOT NULL DEFAULT FALSE,
    backfill_done_at TIMESTAMPTZ
);
INSERT INTO shipped_ledger_meta (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
"""

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS shipped_commits (
            sha TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            workflow_name TEXT NOT NULL,
            repository TEXT NOT NULL,
            repository_key TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            day DATE NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_shipped_commits_rollup
            ON shipped_commits (day, repository_key, workflow_id);
        CREATE TABLE IF NOT EXISTS shipped_pull_requests (
            repository_key TEXT NOT NULL,
            number INT NOT NULL,
            repository TEXT NOT NULL,
            url TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            workflow_name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            opened_day DATE NOT NULL,
            merged_at TIMESTAMPTZ,
            merged_day DATE,
            PRIMARY KEY (repository_key, number)
        );
        CREATE INDEX IF NOT EXISTS ix_shipped_prs_opened
            ON shipped_pull_requests (opened_day, repository_key, workflow_id);
        CREATE INDEX IF NOT EXISTS ix_shipped_prs_merged
            ON shipped_pull_requests (merged_day, repository_key, workflow_id);
        CREATE INDEX IF NOT EXISTS ix_shipped_prs_number ON shipped_pull_requests (number);
        CREATE TABLE IF NOT EXISTS github_pull_request_merges (
            repository_key TEXT NOT NULL,
            number INT NOT NULL,
            repository TEXT NOT NULL,
            repository_id BIGINT,
            merged_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (repository_key, number)
        );
        CREATE INDEX IF NOT EXISTS ix_merges_number ON github_pull_request_merges (number);
        CREATE TABLE IF NOT EXISTS github_repository_aliases (
            repository_key TEXT PRIMARY KEY,
            repository TEXT NOT NULL,
            repository_id BIGINT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_aliases_id ON github_repository_aliases (repository_id);
        CREATE TABLE IF NOT EXISTS shipped_daily (
            day DATE NOT NULL,
            repository_key TEXT NOT NULL,
            repository TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            workflow_name TEXT NOT NULL DEFAULT '',
            commits INT NOT NULL DEFAULT 0,
            prs_opened INT NOT NULL DEFAULT 0,
            prs_merged INT NOT NULL DEFAULT 0,
            prs_opened_merged INT NOT NULL DEFAULT 0,
            PRIMARY KEY (day, repository_key, workflow_id)
        );
        CREATE TABLE IF NOT EXISTS shipped_backfill_pending (
            session_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            attempts INT NOT NULL DEFAULT 0,
            abandoned BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (session_id, execution_id)
        );
        """,
    ),
)

SCHEMA_VERSION = MIGRATIONS[-1][0]
ROLLUP_VERSION = 1
"""Bump when what ``shipped_daily`` derives changes: it is rebuilt from the facts."""

_SCHEMA_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('shipped_ledger:schema', 0))"
_WRITE_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('shipped_ledger:write', 0))"


async def ensure_shipped_ledger_schema(conn: _Conn) -> None:
    """Apply pending migrations, then rebuild the rollup if its version changed.

    Facts are only ever migrated forward, never reset. Safe to run on every
    start and from several processes at once (serialised by an advisory lock).
    """
    async with conn.transaction():
        await conn.execute(_SCHEMA_LOCK)
        await conn.execute(_META)
        applied = int(await conn.fetchval("SELECT schema_version FROM shipped_ledger_meta") or 0)
        for version, ddl in MIGRATIONS:
            if version > applied:
                await conn.execute(ddl)
                await conn.execute("UPDATE shipped_ledger_meta SET schema_version = $1", version)
        rollup = int(await conn.fetchval("SELECT rollup_version FROM shipped_ledger_meta") or 0)
        if rollup != ROLLUP_VERSION:
            await rebuild_rollup(conn)
            await conn.execute("UPDATE shipped_ledger_meta SET rollup_version = $1", ROLLUP_VERSION)


# =============================================================================
# The rollup: recomputed from the facts, key by key
# =============================================================================

_KEY_FILTER = "repository_key = k.repository_key AND workflow_id = k.workflow_id"

_RECOMPUTE = f"""
INSERT INTO shipped_daily (day, repository_key, repository, workflow_id, workflow_name,
                           commits, prs_opened, prs_merged, prs_opened_merged)
SELECT k.day, k.repository_key, COALESCE(f.repository, k.repository_key), k.workflow_id,
       COALESCE(f.workflow_name, ''), f.commits, f.opened, f.merged, f.opened_merged
FROM unnest($1::date[], $2::text[], $3::text[]) AS k(day, repository_key, workflow_id)
CROSS JOIN LATERAL (
    SELECT
        (SELECT count(*) FROM shipped_commits WHERE day = k.day AND {_KEY_FILTER}) AS commits,
        (SELECT count(*) FROM shipped_pull_requests
          WHERE opened_day = k.day AND {_KEY_FILTER}) AS opened,
        (SELECT count(*) FROM shipped_pull_requests
          WHERE merged_day = k.day AND {_KEY_FILTER}) AS merged,
        (SELECT count(*) FROM shipped_pull_requests
          WHERE opened_day = k.day AND merged_at IS NOT NULL AND {_KEY_FILTER}) AS opened_merged,
        (SELECT max(n) FROM (
            SELECT workflow_name AS n FROM shipped_commits WHERE day = k.day AND {_KEY_FILTER}
            UNION ALL
            SELECT workflow_name FROM shipped_pull_requests
             WHERE (opened_day = k.day OR merged_day = k.day) AND {_KEY_FILTER}
        ) names) AS workflow_name,
        (SELECT min(r) FROM (
            SELECT repository AS r FROM shipped_commits WHERE day = k.day AND {_KEY_FILTER}
            UNION ALL
            SELECT repository FROM shipped_pull_requests
             WHERE (opened_day = k.day OR merged_day = k.day) AND {_KEY_FILTER}
        ) repos) AS repository
) f
WHERE f.commits + f.opened + f.merged + f.opened_merged > 0
"""

_DELETE_KEYS = """
DELETE FROM shipped_daily d
USING unnest($1::date[], $2::text[], $3::text[]) AS k(day, repository_key, workflow_id)
WHERE d.day = k.day AND d.repository_key = k.repository_key AND d.workflow_id = k.workflow_id
"""

_ALL_KEYS = """
SELECT day, repository_key, workflow_id FROM shipped_commits
UNION SELECT opened_day, repository_key, workflow_id FROM shipped_pull_requests
UNION SELECT merged_day, repository_key, workflow_id FROM shipped_pull_requests
      WHERE merged_day IS NOT NULL
"""

_REBUILD_CHUNK = 1000


async def recompute(conn: _Conn, keys: Iterable[RollupKey | None]) -> None:
    """Make the rollup rows of ``keys`` equal to what the facts say."""
    distinct = sorted({k for k in keys if k is not None})
    if not distinct:
        return
    days, repos, workflows = (list(column) for column in zip(*distinct, strict=True))
    await conn.execute(_DELETE_KEYS, days, repos, workflows)
    await conn.execute(_RECOMPUTE, days, repos, workflows)


async def rebuild_rollup(conn: _Conn) -> None:
    """The whole rollup again, from the facts. The facts are not touched."""
    await conn.execute("TRUNCATE shipped_daily")
    keys = [
        (r["day"], str(r["repository_key"]), str(r["workflow_id"]))
        for r in await conn.fetch(_ALL_KEYS)
    ]
    for start in range(0, len(keys), _REBUILD_CHUNK):
        await recompute(conn, keys[start : start + _REBUILD_CHUNK])


# =============================================================================
# Writes
# =============================================================================

_COMMIT_OF = """
SELECT observed_at, execution_id, day, repository_key, workflow_id
FROM shipped_commits WHERE sha = $1
"""
_UPSERT_COMMIT = """
INSERT INTO shipped_commits (sha, execution_id, workflow_id, workflow_name, repository,
                             repository_key, observed_at, day)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (sha) DO UPDATE SET
    execution_id = EXCLUDED.execution_id, workflow_id = EXCLUDED.workflow_id,
    workflow_name = EXCLUDED.workflow_name, repository = EXCLUDED.repository,
    repository_key = EXCLUDED.repository_key, observed_at = EXCLUDED.observed_at,
    day = EXCLUDED.day
"""

_PR_OF = """
SELECT created_at, execution_id, opened_day, merged_day, repository_key, workflow_id
FROM shipped_pull_requests WHERE repository_key = $1 AND number = $2
"""
# The merge of the PR (key, number): reported under that slug, or under any
# slug of the same repository id that slug was ever seen with.
_MERGE_FOR_PR = """
SELECT merged_at FROM github_pull_request_merges m
WHERE m.number = $2
  AND (m.repository_key = $1
       OR m.repository_id IN (SELECT repository_id FROM github_repository_aliases
                              WHERE repository_key = $1))
ORDER BY merged_at LIMIT 1
"""
_UPSERT_PR = """
INSERT INTO shipped_pull_requests (repository_key, number, repository, url, execution_id,
    workflow_id, workflow_name, created_at, opened_day, merged_at, merged_day)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (repository_key, number) DO UPDATE SET
    repository = EXCLUDED.repository, url = EXCLUDED.url,
    execution_id = EXCLUDED.execution_id, workflow_id = EXCLUDED.workflow_id,
    workflow_name = EXCLUDED.workflow_name, created_at = EXCLUDED.created_at,
    opened_day = EXCLUDED.opened_day, merged_at = EXCLUDED.merged_at,
    merged_day = EXCLUDED.merged_day
"""

_INSERT_MERGE = """
INSERT INTO github_pull_request_merges (repository_key, number, repository, repository_id, merged_at)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (repository_key, number) DO NOTHING
RETURNING 1
"""
_INSERT_ALIAS = """
INSERT INTO github_repository_aliases (repository_key, repository, repository_id)
VALUES ($1, $2, $3)
ON CONFLICT (repository_key) DO NOTHING
RETURNING 1
"""
# Every unmerged run PR a recorded merge now matches, under any slug of the
# repository: set its merge, return the rollup keys that moved.
_RECONCILE_MERGES = """
UPDATE shipped_pull_requests p
SET merged_at = m.merged_at, merged_day = (m.merged_at AT TIME ZONE 'UTC')::date
FROM github_pull_request_merges m
WHERE p.merged_at IS NULL
  AND p.number = m.number
  AND p.number = ANY($1::int[])
  AND (m.repository_key = p.repository_key
       OR m.repository_id IN (SELECT repository_id FROM github_repository_aliases a
                              WHERE a.repository_key = p.repository_key))
RETURNING p.opened_day, p.merged_day, p.repository_key, p.workflow_id
"""
_NUMBERS_OF_ID = """
SELECT DISTINCT p.number FROM shipped_pull_requests p
JOIN github_repository_aliases a ON a.repository_key = p.repository_key
WHERE a.repository_id = $1 AND p.merged_at IS NULL
"""

_DAILY = """
SELECT day, repository, workflow_id, workflow_name,
       commits, prs_opened, prs_merged, prs_opened_merged
FROM shipped_daily
WHERE day >= $1 AND day <= $2 AND ($3::text IS NULL OR workflow_id = $3)
ORDER BY day, repository_key, workflow_id
"""


def _aware(instant: datetime) -> datetime:
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


def _wins(new_at: datetime, new_id: str, old_at: datetime, old_id: str) -> bool:
    """Earliest observation owns the fact; ties go to the smaller execution id."""
    return (_aware(new_at), new_id) < (_aware(old_at), old_id)


class PostgresShippedLedger:
    """``ShippedLedger`` over the Lane 2 TimescaleDB pool."""

    def __init__(self, pool: Callable[[], asyncpg.Pool | None]) -> None:
        self._pool = pool

    def _require_pool(self) -> asyncpg.Pool:
        pool = self._pool()
        if pool is None:
            raise RuntimeError("The Lane 2 pool is not initialized")
        return pool

    async def record_commit(self, commit: CommitShipped) -> None:
        key = repository_key(commit.repository)
        day = utc_day(commit.committed_at)
        async with self._require_pool().acquire() as conn, conn.transaction():
            await conn.execute(_WRITE_LOCK)
            old = await conn.fetchrow(_COMMIT_OF, commit.sha)
            if old is not None and not _wins(
                commit.committed_at,
                commit.execution_id,
                old["observed_at"],
                str(old["execution_id"]),
            ):
                return
            await conn.execute(
                _UPSERT_COMMIT,
                commit.sha,
                commit.execution_id,
                commit.workflow_id,
                commit.workflow_name,
                commit.repository,
                key,
                commit.committed_at,
                day,
            )
            previous = (
                None
                if old is None
                else (old["day"], str(old["repository_key"]), str(old["workflow_id"]))
            )
            await recompute(conn, [previous, (day, key, commit.workflow_id)])

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None:
        key = repository_key(pr.repository)
        opened_day = utc_day(pr.created_at)
        async with self._require_pool().acquire() as conn, conn.transaction():
            await conn.execute(_WRITE_LOCK)
            old = await conn.fetchrow(_PR_OF, key, pr.number)
            if old is not None and not _wins(
                pr.created_at, pr.execution_id, old["created_at"], str(old["execution_id"])
            ):
                return
            merged_at = await conn.fetchval(_MERGE_FOR_PR, key, pr.number)
            merged_day = utc_day(merged_at) if merged_at is not None else None
            await conn.execute(
                _UPSERT_PR,
                key,
                pr.number,
                pr.repository,
                pr.url,
                pr.execution_id,
                pr.workflow_id,
                pr.workflow_name,
                pr.created_at,
                opened_day,
                merged_at,
                merged_day,
            )
            keys: list[RollupKey | None] = [(opened_day, key, pr.workflow_id)]
            if merged_day is not None:
                keys.append((merged_day, key, pr.workflow_id))
            if old is not None:
                keys += _pr_keys(old["opened_day"], old["merged_day"], old)
            await recompute(conn, keys)

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None:
        key = repository_key(merge.repository)
        async with self._require_pool().acquire() as conn, conn.transaction():
            await conn.execute(_WRITE_LOCK)
            inserted = await conn.fetchval(
                _INSERT_MERGE,
                key,
                merge.number,
                merge.repository,
                merge.repository_id,
                merge.merged_at,
            )
            if inserted is None:
                return
            if merge.repository_id is not None:
                await conn.fetchval(_INSERT_ALIAS, key, merge.repository, merge.repository_id)
            await _reconcile(conn, [merge.number])

    async def record_repository_alias(self, repository: str, repository_id: int) -> None:
        key = repository_key(repository)
        async with self._require_pool().acquire() as conn, conn.transaction():
            await conn.execute(_WRITE_LOCK)
            if await conn.fetchval(_INSERT_ALIAS, key, repository, repository_id) is None:
                return
            numbers = [int(r["number"]) for r in await conn.fetch(_NUMBERS_OF_ID, repository_id)]
            await _reconcile(conn, numbers)

    async def daily(
        self, start: date, end: date, workflow_id: str | None = None
    ) -> Sequence[ShippedDayRow]:
        async with self._require_pool().acquire() as conn:
            rows = await conn.fetch(_DAILY, start, end, workflow_id)
        return [
            ShippedDayRow(
                day=r["day"],
                repository=str(r["repository"]),
                workflow_id=str(r["workflow_id"]),
                workflow_name=str(r["workflow_name"]),
                commits=int(r["commits"]),
                prs_opened=int(r["prs_opened"]),
                prs_merged=int(r["prs_merged"]),
                prs_opened_merged=int(r["prs_opened_merged"]),
            )
            for r in rows
        ]


def _pr_keys(
    opened_day: date, merged_day: date | None, row: asyncpg.Record
) -> list[RollupKey | None]:
    who = (str(row["repository_key"]), str(row["workflow_id"]))
    return [(opened_day, *who), None if merged_day is None else (merged_day, *who)]


async def _reconcile(conn: _Conn, numbers: Sequence[int]) -> None:
    """Count every merge that now matches an unmerged run PR with these numbers."""
    if not numbers:
        return
    moved = await conn.fetch(_RECONCILE_MERGES, list(numbers))
    keys: list[RollupKey | None] = []
    for r in moved:
        keys += _pr_keys(r["opened_day"], r["merged_day"], r)
    await recompute(conn, keys)
