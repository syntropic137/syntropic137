"""Replay Lane 2 history into the shipped ledger: paged, resumable, bounded.

WHAT IT READS. Every (session, execution) the day rollup knows, in pages of
``session_page`` by ``session_id``, and for each one its ``git_commit`` rows
and the tool rows whose text can be a ``gh pr create`` or a PR URL, in pages
of ``row_page`` in a total order (time, type, content). Every agent_events read pins ``session_id``, so
a compressed chunk discards every other session's segment.

BOUNDED. One query in flight at a time; at most one page of sessions and one
page of rows in memory; after ``tick_seconds`` of work it sleeps ``pause``
seconds and continues, so it never monopolises the database or the loop.

RESUMABLE. ``shipped_ledger_meta.backfill_cursor`` is the last session fully
replayed, written after every page: a restart continues from it, and replays
of the page in flight are harmless (every ledger write is idempotent by
identity, and attribution is a rule, not an arrival order, so the order this
walk happens to take changes nothing).

NOTHING IS SKIPPED SILENTLY. A session whose execution the read model does
not know yet is kept in ``shipped_backfill_pending`` and retried
(``rounds_per_run`` rounds per run, ``retry_after`` apart, and again on every
later start); only after ``max_attempts`` attempts across runs is it marked
``abandoned`` (permanently unattributable). The backfill is done only when the
walk finished and nothing retryable is pending.

PREVIEWS, NOT FULL OUTPUT. History keeps only 500-character previews, so the
same strict parser runs on them and anything a preview may have cut is
skipped: an input that is not complete JSON, an output at the limit. It can
undercount PRs, never invent one. Merges are not in history at all.

COST. Roughly one read of agent_events for the sessions that ran executions,
once per ``BACKFILL_VERSION``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import (
    CommitShipped,
    CreatedPullRequest,
    ExecutionAttribution,
    PullRequestOpened,
    created_pull_requests,
)
from syn_shared.events import GIT_COMMIT, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from datetime import datetime

    import asyncpg

    from syn_adapters.events.shipped_ledger import PostgresShippedLedger

logger = logging.getLogger(__name__)

BACKFILL_VERSION = 1
"""Bump when what the backfill extracts changes: it walks history again (facts are kept)."""

PREVIEW_LIMIT = 500

type AttributionLookup = Callable[[Sequence[str]], Awaitable[Mapping[str, ExecutionAttribution]]]


@dataclass(frozen=True)
class BackfillLimits:
    session_page: int = 100
    row_page: int = 2000
    tick_seconds: float = 10.0
    pause: float = 1.0
    retry_after: float = 60.0
    rounds_per_run: int = 3
    """Retry rounds over the unattributed sessions in one run, ``retry_after`` apart."""
    max_attempts: int = 10
    """Attempts across all runs before a session is abandoned as unattributable."""


@dataclass
class BackfillReport:
    facts: int = 0
    sessions: int = 0
    pending: int = 0
    abandoned: int = 0
    done: bool = False


_SESSIONS = """
SELECT session_id, array_agg(DISTINCT execution_id ORDER BY execution_id) AS executions
FROM agent_event_day_rollup
WHERE execution_id IS NOT NULL AND execution_id <> ''
  AND ($1::text IS NULL OR session_id > $1)
GROUP BY session_id
ORDER BY session_id
LIMIT $2
"""

_SESSION_ROWS = """
SELECT time, event_type, data
FROM agent_events
WHERE session_id = $1
  AND execution_id = $2
  AND event_type = ANY($3::text[])
  AND (event_type = $4
       OR data::text LIKE '%gh pr create%'
       OR data->>'output_preview' LIKE '%/pull/%')
ORDER BY time, event_type, md5(data::text)
LIMIT $5 OFFSET $6
"""


class _Clock:
    """Work for ``tick_seconds``, then yield ``pause``: the bound on the backfill."""

    def __init__(self, limits: BackfillLimits, sleep: Callable[[float], Awaitable[None]]) -> None:
        self._limits = limits
        self._sleep = sleep
        self._started = time.monotonic()

    async def checkpoint(self) -> None:
        if time.monotonic() - self._started >= self._limits.tick_seconds:
            await self._sleep(self._limits.pause)
            self._started = time.monotonic()


@dataclass
class _Session:
    """One session's replay: tool starts waiting for their result, across pages."""

    commands: dict[str, str] = field(default_factory=dict)
    facts: int = 0


async def run_backfill(
    pool: asyncpg.Pool,
    ledger: PostgresShippedLedger,
    attributions: AttributionLookup,
    limits: BackfillLimits | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> BackfillReport:
    """Walk history into the ledger until done; resumes wherever it stopped."""
    limits = limits or BackfillLimits()
    clock = _Clock(limits, sleep)
    report = BackfillReport()
    async with pool.acquire() as conn:
        meta = await conn.fetchrow(
            "SELECT backfill_version, backfill_cursor, backfill_sessions_walked, backfill_done_at"
            " FROM shipped_ledger_meta"
        )
        if meta is None:
            return report
        if int(meta["backfill_version"]) != BACKFILL_VERSION:
            await conn.execute(
                "UPDATE shipped_ledger_meta SET backfill_version = $1, backfill_cursor = NULL,"
                " backfill_sessions_walked = FALSE, backfill_done_at = NULL",
                BACKFILL_VERSION,
            )
            await conn.execute("DELETE FROM shipped_backfill_pending")
            meta = None
        elif meta["backfill_done_at"] is not None:
            report.done = True
            return report
    cursor = None if meta is None else meta["backfill_cursor"]
    walked = False if meta is None else bool(meta["backfill_sessions_walked"])
    if not walked:
        await _walk(pool, ledger, attributions, limits, clock, report, cursor)
    await _retry_pending(pool, ledger, attributions, limits, clock, report, sleep)
    return report


async def _walk(
    pool: asyncpg.Pool,
    ledger: PostgresShippedLedger,
    attributions: AttributionLookup,
    limits: BackfillLimits,
    clock: _Clock,
    report: BackfillReport,
    cursor: str | None,
) -> None:
    while True:
        async with pool.acquire() as conn:
            sessions = await conn.fetch(_SESSIONS, cursor, limits.session_page)
        if not sessions:
            break
        page = [(str(r["session_id"]), str(e)) for r in sessions for e in r["executions"]]
        found = await attributions(sorted({e for _, e in page}))
        for session_id, execution_id in page:
            attribution = found.get(execution_id)
            if attribution is None:
                await _keep_pending(pool, session_id, execution_id)
                continue
            report.facts += await _replay_session(
                pool, ledger, attribution, session_id, limits, clock
            )
            report.sessions += 1
        cursor = page[-1][0]
        async with pool.acquire() as conn:
            await conn.execute("UPDATE shipped_ledger_meta SET backfill_cursor = $1", cursor)
        await clock.checkpoint()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE shipped_ledger_meta SET backfill_sessions_walked = TRUE")


async def _keep_pending(pool: asyncpg.Pool, session_id: str, execution_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO shipped_backfill_pending (session_id, execution_id) VALUES ($1, $2)"
            " ON CONFLICT DO NOTHING",
            session_id,
            execution_id,
        )


_PENDING_PAGE = """
SELECT session_id, execution_id FROM shipped_backfill_pending
WHERE NOT abandoned AND (session_id, execution_id) > ($1, $2)
ORDER BY session_id, execution_id LIMIT $3
"""


async def _retry_pending(
    pool: asyncpg.Pool,
    ledger: PostgresShippedLedger,
    attributions: AttributionLookup,
    limits: BackfillLimits,
    clock: _Clock,
    report: BackfillReport,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Retry every unattributed session for ``rounds_per_run`` rounds, ``retry_after`` apart.

    What is still unattributed stays pending for the next run; only after
    ``max_attempts`` attempts across runs is a session abandoned.
    """
    for attempt in range(limits.rounds_per_run):
        if attempt > 0:
            await sleep(limits.retry_after)
        if not await _retry_round(pool, ledger, attributions, limits, clock, report):
            break
    async with pool.acquire() as conn:
        report.pending = int(
            await conn.fetchval("SELECT count(*) FROM shipped_backfill_pending WHERE NOT abandoned")
            or 0
        )
        report.abandoned = int(
            await conn.fetchval("SELECT count(*) FROM shipped_backfill_pending WHERE abandoned")
            or 0
        )
        if report.pending == 0:
            await conn.execute("UPDATE shipped_ledger_meta SET backfill_done_at = now()")
            report.done = True
    logger.info(
        "Shipped ledger backfill: %d facts from %d sessions; %d pending, %d unattributable",
        report.facts,
        report.sessions,
        report.pending,
        report.abandoned,
    )


async def _retry_round(
    pool: asyncpg.Pool,
    ledger: PostgresShippedLedger,
    attributions: AttributionLookup,
    limits: BackfillLimits,
    clock: _Clock,
    report: BackfillReport,
) -> bool:
    """One pass over every pending session, a page at a time; whether any was pending."""
    after = ("", "")
    seen = False
    while True:
        async with pool.acquire() as conn:
            page = [
                (str(r["session_id"]), str(r["execution_id"]))
                for r in await conn.fetch(_PENDING_PAGE, *after, limits.session_page)
            ]
        if not page:
            return seen
        seen = True
        found = await attributions(sorted({e for _, e in page}))
        for session_id, execution_id in page:
            await _retry_one(
                pool,
                ledger,
                found.get(execution_id),
                session_id,
                execution_id,
                limits,
                clock,
                report,
            )
        after = page[-1]
        await clock.checkpoint()


async def _retry_one(
    pool: asyncpg.Pool,
    ledger: PostgresShippedLedger,
    attribution: ExecutionAttribution | None,
    session_id: str,
    execution_id: str,
    limits: BackfillLimits,
    clock: _Clock,
    report: BackfillReport,
) -> None:
    if attribution is None:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE shipped_backfill_pending SET attempts = attempts + 1,"
                " abandoned = attempts + 1 >= $3 WHERE session_id = $1 AND execution_id = $2",
                session_id,
                execution_id,
                limits.max_attempts,
            )
        return
    report.facts += await _replay_session(pool, ledger, attribution, session_id, limits, clock)
    report.sessions += 1
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM shipped_backfill_pending WHERE session_id = $1 AND execution_id = $2",
            session_id,
            execution_id,
        )


async def _replay_session(
    pool: asyncpg.Pool,
    ledger: PostgresShippedLedger,
    attribution: ExecutionAttribution,
    session_id: str,
    limits: BackfillLimits,
    clock: _Clock,
) -> int:
    """One session's rows, a page at a time, in a total order.

    Ordered by time, then type, then content: rows equal on all three are
    the same observation twice, so which of them a page boundary splits
    changes nothing. Only the gh/URL-shaped and commit rows are selected, so
    a session's pages are few and the OFFSET stays small.
    """
    state = _Session()
    offset = 0
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _SESSION_ROWS,
                session_id,
                attribution.execution_id,
                [GIT_COMMIT, TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED],
                GIT_COMMIT,
                limits.row_page,
                offset,
            )
        for r in rows:
            await _replay_row(ledger, attribution, state, r)
        if len(rows) < limits.row_page:
            return state.facts
        offset += len(rows)
        await clock.checkpoint()


async def _replay_row(
    ledger: PostgresShippedLedger,
    attribution: ExecutionAttribution,
    state: _Session,
    r: asyncpg.Record,
) -> None:
    data = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"])
    event_type = str(r["event_type"])
    if event_type == GIT_COMMIT:
        sha, repo = _commit_facts(data)
        state.facts += await _replay_commit(ledger, attribution, sha, repo, r["time"])
    elif event_type == TOOL_EXECUTION_STARTED:
        command = _preview_command(data.get("input_preview"))
        if command is not None:
            state.commands[str(data.get("tool_use_id"))] = command
    else:
        command = state.commands.pop(str(data.get("tool_use_id")), None)
        for created in _preview_created(command, data.get("success"), data.get("output_preview")):
            state.facts += await _replay_pr(ledger, attribution, created, r["time"])


def _commit_facts(data: object) -> tuple[object, object]:
    """(sha, repo) of a git_commit row in either payload shape."""
    if not isinstance(data, dict):
        return None, None
    git = data.get("git")
    facts = git if isinstance(git, dict) else data
    return facts.get("sha") or facts.get("commit_hash"), facts.get("repo")


def _preview_created(
    command: str | None, success: object, output: object
) -> list[CreatedPullRequest]:
    """The PRs a historic call created, judged only on an output the preview did not cut."""
    if command is None or not isinstance(output, str) or len(output) >= PREVIEW_LIMIT:
        return []
    return created_pull_requests(command, success is True, output)


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
    created: CreatedPullRequest,
    at: datetime,
) -> int:
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
