"""The shipped ledger in TimescaleDB, beside ``agent_events`` (Lane 2).

Implements ``ShippedLedger`` (``syn_domain...orchestration._shared.shipped_ledger``):
three fact tables keyed by identity and the ``shipped_daily`` rollup the
"Shipped by agents" read path reads. See that module for the semantics; this
one is how they hold in SQL.

IDEMPOTENT: each fact is inserted ``ON CONFLICT DO NOTHING`` and the rollup is
touched only when the insert actually happened, in the same transaction, so a
redelivered or replayed fact changes nothing.

ORDER-INDEPENDENT: a PR and its merge can arrive in either order. Both writes
take the same transaction-scoped advisory lock on the PR's identity before
reading the other side, so two concurrent writers cannot each miss the other.

VERSIONED: ``SHIPPED_LEDGER_VERSION`` is stored in ``shipped_ledger_meta``.
A version change drops and recreates the tables and clears the backfill mark,
so the next start rebuilds them from the Lane 2 sources (``backfill``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import (
    CommitShipped,
    CreatedPullRequest,
    ExecutionAttribution,
    PullRequestMerged,
    PullRequestOpened,
    ShippedDayRow,
    created_pull_request,
    repository_key,
    utc_day,
)
from syn_shared.events import GIT_COMMIT, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from datetime import date, datetime

    import asyncpg

logger = logging.getLogger(__name__)

SHIPPED_LEDGER_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shipped_ledger_meta (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version INT NOT NULL,
    backfilled_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS shipped_commits (
    sha TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    day DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS shipped_pull_requests (
    repository_key TEXT NOT NULL,
    number INT NOT NULL,
    repository TEXT NOT NULL,
    url TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    opened_day DATE NOT NULL,
    PRIMARY KEY (repository_key, number)
);
CREATE TABLE IF NOT EXISTS github_pull_request_merges (
    repository_key TEXT NOT NULL,
    number INT NOT NULL,
    repository TEXT NOT NULL,
    merged_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (repository_key, number)
);
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
"""

_TABLES = (
    "shipped_daily",
    "shipped_commits",
    "shipped_pull_requests",
    "github_pull_request_merges",
)

# One counter of one rollup row, incremented. ``{column}`` is one of four
# names fixed in this module, never caller input.
_BUMP = """
INSERT INTO shipped_daily (day, repository_key, repository, workflow_id, workflow_name, {column})
VALUES ($1, $2, $3, $4, $5, 1)
ON CONFLICT (day, repository_key, workflow_id) DO UPDATE
SET {column} = shipped_daily.{column} + 1,
    workflow_name = CASE WHEN EXCLUDED.workflow_name <> ''
                         THEN EXCLUDED.workflow_name ELSE shipped_daily.workflow_name END
"""

_RECORD_COMMIT = """
WITH inserted AS (
    INSERT INTO shipped_commits (sha, execution_id, workflow_id, repository, day)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (sha) DO NOTHING
    RETURNING day, repository, workflow_id
)
INSERT INTO shipped_daily (day, repository_key, repository, workflow_id, workflow_name, commits)
SELECT day, lower(repository), repository, workflow_id, $6, 1 FROM inserted
ON CONFLICT (day, repository_key, workflow_id) DO UPDATE
SET commits = shipped_daily.commits + 1,
    workflow_name = CASE WHEN EXCLUDED.workflow_name <> ''
                         THEN EXCLUDED.workflow_name ELSE shipped_daily.workflow_name END
"""

_LOCK_PR = "SELECT pg_advisory_xact_lock(hashtextextended($1::text || '#' || $2::text, 0))"

_INSERT_PR = """
INSERT INTO shipped_pull_requests
    (repository_key, number, repository, url, execution_id, workflow_id, workflow_name, opened_day)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (repository_key, number) DO NOTHING
RETURNING 1
"""

_INSERT_MERGE = """
INSERT INTO github_pull_request_merges (repository_key, number, repository, merged_at)
VALUES ($1, $2, $3, $4)
ON CONFLICT (repository_key, number) DO NOTHING
RETURNING 1
"""

_MERGE_OF = (
    "SELECT merged_at FROM github_pull_request_merges WHERE repository_key = $1 AND number = $2"
)
_PR_OF = """
SELECT repository, workflow_id, workflow_name, opened_day
FROM shipped_pull_requests WHERE repository_key = $1 AND number = $2
"""

_DAILY = """
SELECT day, repository, workflow_id, workflow_name,
       commits, prs_opened, prs_merged, prs_opened_merged
FROM shipped_daily
WHERE day >= $1 AND day <= $2 AND ($3::text IS NULL OR workflow_id = $3)
ORDER BY day, repository_key, workflow_id
"""


async def ensure_shipped_ledger_schema(
    conn: asyncpg.Connection | asyncpg.pool.PoolConnectionProxy,
) -> None:
    """Create the ledger; on a version change, recreate it empty for a rebuild."""
    await conn.execute(_SCHEMA)
    stored = await conn.fetchval("SELECT version FROM shipped_ledger_meta WHERE id = 1")
    if stored == SHIPPED_LEDGER_VERSION:
        return
    async with conn.transaction():
        if stored is not None:
            for table in _TABLES:
                await conn.execute(f"TRUNCATE {table}")
        await conn.execute(
            "INSERT INTO shipped_ledger_meta (id, version, backfilled_at) VALUES (1, $1, NULL) "
            "ON CONFLICT (id) DO UPDATE SET version = EXCLUDED.version, backfilled_at = NULL",
            SHIPPED_LEDGER_VERSION,
        )


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
        async with self._require_pool().acquire() as conn:
            await conn.execute(
                _RECORD_COMMIT,
                commit.sha,
                commit.execution_id,
                commit.workflow_id,
                commit.repository,
                utc_day(commit.committed_at),
                commit.workflow_name,
            )

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None:
        key = repository_key(pr.repository)
        opened_day = utc_day(pr.created_at)
        async with self._require_pool().acquire() as conn, conn.transaction():
            await conn.execute(_LOCK_PR, key, str(pr.number))
            inserted = await conn.fetchval(
                _INSERT_PR,
                key,
                pr.number,
                pr.repository,
                pr.url,
                pr.execution_id,
                pr.workflow_id,
                pr.workflow_name,
                opened_day,
            )
            if inserted is None:
                return
            row = (key, pr.repository, pr.workflow_id, pr.workflow_name)
            await _bump(conn, "prs_opened", opened_day, row)
            merged_at = await conn.fetchval(_MERGE_OF, key, pr.number)
            if merged_at is not None:
                await _bump(conn, "prs_opened_merged", opened_day, row)
                await _bump(conn, "prs_merged", utc_day(merged_at), row)

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None:
        key = repository_key(merge.repository)
        async with self._require_pool().acquire() as conn, conn.transaction():
            await conn.execute(_LOCK_PR, key, str(merge.number))
            inserted = await conn.fetchval(
                _INSERT_MERGE, key, merge.number, merge.repository, merge.merged_at
            )
            if inserted is None:
                return
            pr = await conn.fetchrow(_PR_OF, key, merge.number)
            if pr is None:
                return  # not a run's PR (yet): counted if and when one arrives
            row = (key, str(pr["repository"]), str(pr["workflow_id"]), str(pr["workflow_name"]))
            await _bump(conn, "prs_opened_merged", pr["opened_day"], row)
            await _bump(conn, "prs_merged", utc_day(merge.merged_at), row)

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


async def _bump(
    conn: asyncpg.pool.PoolConnectionProxy, column: str, day: date, row: tuple[str, str, str, str]
) -> None:
    key, repository, workflow_id, workflow_name = row
    await conn.execute(
        _BUMP.format(column=column), day, key, repository, workflow_id, workflow_name
    )


# =============================================================================
# Backfill: replay the Lane 2 sources once
# =============================================================================
#
# COST. One pass over agent_events, visiting each session that has an
# execution in batches of BACKFILL_SESSION_BATCH (session_id = ANY: a
# compressed chunk discards every other session's segment). Each batch reads
# only the session's git_commit rows and the tool rows whose text can be a
# `gh pr create` or a PR URL, so what crosses the wire is small; what the
# database decompresses is every segment of those sessions once. Roughly one
# full read of agent_events, done once per ledger version, in the background.
#
# PREVIEWS, NOT FULL OUTPUT. History holds only the 500-character previews, so
# the backfill applies the same strict parser to them and skips anything a
# preview may have cut: an input that is not complete JSON, an output at the
# preview limit. Live ingestion reads the full command and output; the
# backfill can only undercount, never invent a PR.
#
# MERGES ARE NOT IN LANE 2 HISTORY: before the merge observer ran, no store
# kept them, so PRs merged before it was deployed have no merge (#1852).

BACKFILL_SESSION_BATCH = 200
PREVIEW_LIMIT = 500

_BACKFILL_SESSIONS = """
SELECT DISTINCT session_id, execution_id
FROM agent_event_day_rollup
WHERE execution_id IS NOT NULL AND execution_id <> ''
ORDER BY session_id
"""

_BACKFILL_ROWS = """
SELECT time, session_id, execution_id, event_type, data
FROM agent_events
WHERE session_id = ANY($1::text[])
  AND event_type = ANY($2::text[])
  AND (event_type = $3
       OR data::text LIKE '%gh pr create%'
       OR data->>'output_preview' LIKE '%/pull/%')
ORDER BY time
"""


type AttributionLookup = Callable[[Sequence[str]], Awaitable[Mapping[str, ExecutionAttribution]]]


async def backfill(
    pool: asyncpg.Pool, ledger: PostgresShippedLedger, attributions: AttributionLookup
) -> int:
    """Rebuild the ledger from Lane 2 history once per version; facts replayed."""
    async with pool.acquire() as conn:
        done = await conn.fetchval("SELECT backfilled_at FROM shipped_ledger_meta WHERE id = 1")
        if done is not None:
            return 0
        sessions = await conn.fetch(_BACKFILL_SESSIONS)
    replayed = 0
    ids = [str(r["session_id"]) for r in sessions]
    for start in range(0, len(ids), BACKFILL_SESSION_BATCH):
        batch = ids[start : start + BACKFILL_SESSION_BATCH]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _BACKFILL_ROWS,
                batch,
                [GIT_COMMIT, TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED],
                GIT_COMMIT,
            )
        found = await attributions(sorted({str(r["execution_id"]) for r in rows}))
        replayed += await _replay(ledger, rows, found)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE shipped_ledger_meta SET backfilled_at = now() WHERE id = 1")
    logger.info("Shipped ledger backfilled: %d facts from %d sessions", replayed, len(ids))
    return replayed


async def _replay(
    ledger: PostgresShippedLedger,
    rows: Sequence[asyncpg.Record],
    attributions: Mapping[str, ExecutionAttribution],
) -> int:
    replay = _Replay(ledger, attributions)
    for r in rows:
        await replay.row(r)
    return replay.replayed


class _Replay:
    """One batch of history rows, in time order, into the ledger."""

    def __init__(
        self, ledger: PostgresShippedLedger, attributions: Mapping[str, ExecutionAttribution]
    ) -> None:
        self._ledger = ledger
        self._attributions = attributions
        self._commands: dict[tuple[str, str], str] = {}
        self.replayed = 0

    async def row(self, r: asyncpg.Record) -> None:
        attribution = self._attributions.get(str(r["execution_id"]))
        if attribution is None:
            return
        data = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"])
        call = (str(r["session_id"]), str(data.get("tool_use_id")))
        event_type = str(r["event_type"])
        if event_type == GIT_COMMIT:
            sha, repo = _commit_facts(data)
            self.replayed += await _replay_commit(self._ledger, attribution, sha, repo, r["time"])
        elif event_type == TOOL_EXECUTION_STARTED:
            command = _preview_command(data.get("input_preview"))
            if command is not None:
                self._commands[call] = command
        else:
            created = _preview_created(
                self._commands.pop(call, None), data.get("success"), data.get("output_preview")
            )
            self.replayed += await _replay_pr(self._ledger, attribution, created, r["time"])


def _commit_facts(data: object) -> tuple[object, object]:
    """(sha, repo) of a git_commit row in either payload shape."""
    if not isinstance(data, dict):
        return None, None
    git = data.get("git")
    facts = git if isinstance(git, dict) else data
    return facts.get("sha") or facts.get("commit_hash"), facts.get("repo")


def _preview_created(
    command: str | None, success: object, output: object
) -> CreatedPullRequest | None:
    """The PR a historic call created, judged only on an output the preview did not cut."""
    if command is None or not isinstance(output, str) or len(output) >= PREVIEW_LIMIT:
        return None
    return created_pull_request(command, success is True, output)


async def _replay_commit(
    ledger: PostgresShippedLedger,
    attribution: ExecutionAttribution,
    sha: object,
    repo: object,
    at: datetime,
) -> int:
    repository = attribution.repository_for(str(repo) if repo else None)
    if not sha or repository is None:
        return 0
    await ledger.record_commit(
        CommitShipped(
            sha=str(sha),
            execution_id=attribution.execution_id,
            workflow_id=attribution.workflow_id,
            workflow_name=attribution.workflow_name,
            repository=repository,
            committed_at=at,
        )
    )
    return 1


async def _replay_pr(
    ledger: PostgresShippedLedger,
    attribution: ExecutionAttribution,
    created: CreatedPullRequest | None,
    at: datetime,
) -> int:
    if created is None:
        return 0
    await ledger.record_pull_request_opened(
        PullRequestOpened(
            repository=created.repository,
            number=created.number,
            url=created.url,
            execution_id=attribution.execution_id,
            workflow_id=attribution.workflow_id,
            workflow_name=attribution.workflow_name,
            created_at=at,
        )
    )
    return 1


def _preview_command(preview: object) -> str | None:
    """The command in a tool start's preview, or None when it may be cut.

    Claude stores ``json.dumps(tool_input)[:500]``: only complete JSON is
    trusted. Codex stores the command string itself: trusted below the limit.
    """
    if not isinstance(preview, str) or len(preview) >= PREVIEW_LIMIT:
        return None
    try:
        parsed = json.loads(preview)
    except ValueError:
        return preview
    if isinstance(parsed, dict):
        command = parsed.get("command")
        return command if isinstance(command, str) else None
    return None
