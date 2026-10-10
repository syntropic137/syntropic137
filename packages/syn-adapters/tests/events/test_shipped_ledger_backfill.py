"""The backfill replays Lane 2 history into the ledger: strictly, paged, resumably.

MARKED ``integration``: needs a real PostgreSQL with agent_events and its day
rollup trigger, which is how the backfill finds the sessions to visit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.events.shipped_backfill import BackfillLimits, run_backfill
from syn_domain.contexts.orchestration import ExecutionAttribution
from syn_shared.events import GIT_COMMIT, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from syn_tests.fixtures.infrastructure import TestInfrastructure

    from syn_adapters.events import AgentEventStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

RUN = uuid4().hex[:8]
SESSIONS = [f"shipbf-{RUN}-{i}" for i in range(3)]
EXEC = f"shipbfx-{RUN}"
REPO = f"acme/bf-{RUN}"
AT = datetime(2024, 3, 5, 10, tzinfo=UTC)
FAST = BackfillLimits(
    session_page=1, row_page=2, tick_seconds=0.0, pause=0.0, retry_after=0.0, max_attempts=2
)
_LEDGER_TABLES = (
    "TRUNCATE shipped_daily, shipped_commits, shipped_pull_requests,"
    " github_pull_request_merges, github_repository_aliases, shipped_backfill_pending"
)


class _Attributions:
    def __init__(self, known: bool) -> None:
        self.known = known

    async def __call__(self, ids: Sequence[str]) -> Mapping[str, ExecutionAttribution]:
        if not self.known:
            return {}
        return {i: ExecutionAttribution(i, "wf-bf", "Backfill", (REPO,)) for i in ids if i == EXEC}


def _rows(session_index: int) -> list[tuple[datetime, str, str]]:
    at = AT + timedelta(days=session_index)
    url = f"https://github.com/{REPO}/pull/{10 + session_index}"
    start = {"input_preview": json.dumps({"command": "gh pr create --fill"})}
    rows = [
        (
            at,
            GIT_COMMIT,
            {"git": {"sha": f"sha-{RUN}-{session_index}", "repo": REPO.split("/")[1]}},
        ),
        (at, TOOL_EXECUTION_STARTED, {"tool_use_id": "t1", **start}),
        (
            at + timedelta(seconds=2),
            TOOL_EXECUTION_COMPLETED,
            {"tool_use_id": "t1", "success": True, "output_preview": f"{url}\n"},
        ),
        # A cut preview is never parsed into a PR.
        (at, TOOL_EXECUTION_STARTED, {"tool_use_id": "t2", **start}),
        (
            at + timedelta(seconds=3),
            TOOL_EXECUTION_COMPLETED,
            {"tool_use_id": "t2", "success": True, "output_preview": "x" * 480 + f"\n{url}9"},
        ),
        # A failed create, and a create followed by an echo of a URL.
        (at, TOOL_EXECUTION_STARTED, {"tool_use_id": "t3", **start}),
        (
            at + timedelta(seconds=4),
            TOOL_EXECUTION_COMPLETED,
            {"tool_use_id": "t3", "success": False, "output_preview": url + "8"},
        ),
        (
            at,
            TOOL_EXECUTION_STARTED,
            {
                "tool_use_id": "t4",
                "input_preview": json.dumps({"command": f"gh pr create || echo {url}7"}),
            },
        ),
        (
            at + timedelta(seconds=5),
            TOOL_EXECUTION_COMPLETED,
            {"tool_use_id": "t4", "success": True, "output_preview": url + "7"},
        ),
    ]
    return [(when, event_type, json.dumps(data)) for when, event_type, data in rows]


@pytest.fixture
async def store(test_infrastructure: TestInfrastructure) -> AsyncIterator[AgentEventStore]:
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(_LEDGER_TABLES)
        await conn.execute(
            "UPDATE shipped_ledger_meta SET backfill_version = 0, backfill_cursor = NULL,"
            " backfill_sessions_walked = FALSE, backfill_done_at = NULL"
        )
        for index, session in enumerate(SESSIONS):
            for at, event_type, data in _rows(index):
                await conn.execute(
                    "INSERT INTO agent_events (time, event_type, session_id, execution_id, data)"
                    " VALUES ($1, $2, $3, $4, $5::jsonb)",
                    at,
                    event_type,
                    session,
                    EXEC,
                    data,
                )
    try:
        yield store
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_events WHERE session_id = ANY($1)", SESSIONS)
            await conn.execute(
                "DELETE FROM agent_event_day_rollup WHERE session_id = ANY($1)", SESSIONS
            )
            await conn.execute(_LEDGER_TABLES)
            await conn.execute(
                "UPDATE shipped_ledger_meta SET backfill_done_at = NULL, backfill_cursor = NULL,"
                " backfill_sessions_walked = FALSE"
            )
        await store.close()


async def _mine(store: AgentEventStore) -> list[tuple[str, int, int]]:
    rows = await store.shipped_ledger.daily(AT.date(), (AT + timedelta(days=5)).date(), "wf-bf")
    return [(r.repository, r.commits, r.prs_opened) for r in rows]


async def test_pages_strictly_and_is_done_once(store: AgentEventStore) -> None:
    pool = store.pool
    assert pool is not None
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    report = await run_backfill(pool, store.shipped_ledger, _Attributions(True), FAST, sleep)
    assert report.done
    assert await _mine(store) == [(REPO, 1, 1)] * 3  # one commit, one strict PR per session
    assert pauses  # it yielded between pages instead of running unbounded
    again = await run_backfill(pool, store.shipped_ledger, _Attributions(True), FAST, sleep)
    assert again.done and again.facts == 0  # done means done: nothing re-read


async def test_unattributable_sessions_are_kept_and_retried_on_the_next_run(
    store: AgentEventStore,
) -> None:
    pool = store.pool
    assert pool is not None

    async def sleep(_: float) -> None:
        return None

    patient = BackfillLimits(
        session_page=1,
        row_page=2,
        tick_seconds=0.0,
        pause=0.0,
        retry_after=0.0,
        rounds_per_run=1,
        max_attempts=5,
    )
    # The read model has not caught up: nothing replayed, kept, not done.
    first = await run_backfill(pool, store.shipped_ledger, _Attributions(False), patient, sleep)
    assert not first.done and first.facts == 0
    assert await _pending(store) == len(SESSIONS)
    # The next start finds the executions: replayed, and no longer pending.
    await run_backfill(pool, store.shipped_ledger, _Attributions(True), patient, sleep)
    assert await _pending(store) == 0
    assert await _mine(store) == [(REPO, 1, 1)] * 3


async def _pending(store: AgentEventStore) -> int:
    assert store.pool is not None
    async with store.pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM shipped_backfill_pending WHERE session_id = ANY($1)"
                " AND NOT abandoned",
                SESSIONS,
            )
        )


async def test_it_resumes_from_its_cursor(store: AgentEventStore) -> None:
    pool = store.pool
    assert pool is not None

    class _Stop(Exception):
        pass

    async def stop_after_first_page(_: float) -> None:
        async with pool.acquire() as conn:
            if await conn.fetchval("SELECT backfill_cursor FROM shipped_ledger_meta") is not None:
                raise _Stop

    with pytest.raises(_Stop):
        await run_backfill(
            pool, store.shipped_ledger, _Attributions(True), FAST, stop_after_first_page
        )
    async with pool.acquire() as conn:
        cursor = await conn.fetchval("SELECT backfill_cursor FROM shipped_ledger_meta")
    assert cursor is not None

    async def sleep(_: float) -> None:
        return None

    report = await run_backfill(pool, store.shipped_ledger, _Attributions(True), FAST, sleep)
    assert report.done
    assert await _mine(store) == [(REPO, 1, 1)] * 3
