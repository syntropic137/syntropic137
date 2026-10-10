"""TimescaleCommitSightings against a real agent_events table.

The SQL decides what a commit IS for the "Shipped by agents" tile, so it is
asked of PostgreSQL, not of a double: every sha spelling the timeline reads,
one count per sha on its first UTC day, nothing without an execution, and a
UTC day whatever the reading connection's zone.

MARKED ``integration``: needs a real PostgreSQL.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_domain.contexts.orchestration.slices.shipped_metrics import (
    TimescaleCommitSightings,
    TimescalePullRequestSightings,
)
from syn_shared.events import (
    GIT_COMMIT,
    GITHUB_PULL_REQUEST_MERGED,
    SESSION_STARTED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration

_RUN = uuid4().hex[:8]
SESSION = f"shipq-{_RUN}"
EXEC = f"shipx-{_RUN}"
SINCE = datetime(2023, 6, 1, tzinfo=UTC)
UNTIL = datetime(2023, 6, 8, tzinfo=UTC)

# (time, execution_id, data) -> seeded as git_commit unless noted.
_ROWS: list[tuple[datetime, str | None, str]] = [
    # v2 shape, first seen on 06-01 at 23:30Z (06-02 in Kolkata), again on 06-03.
    (datetime(2023, 6, 1, 23, 30, tzinfo=UTC), EXEC, f'{{"git": {{"sha": "v2-{_RUN}"}}}}'),
    (datetime(2023, 6, 3, 9, 0, tzinfo=UTC), EXEC, f'{{"git": {{"sha": "v2-{_RUN}"}}}}'),
    # legacy top-level and context spellings
    (datetime(2023, 6, 2, 12, 0, tzinfo=UTC), EXEC, f'{{"sha": "top-{_RUN}"}}'),
    (datetime(2023, 6, 2, 12, 1, tzinfo=UTC), EXEC, f'{{"context": {{"sha": "ctx-{_RUN}"}}}}'),
    # no sha in any spelling: skipped
    (datetime(2023, 6, 2, 12, 2, tzinfo=UTC), EXEC, '{"git": {"sha": ""}}'),
    # push webhook shape: no execution, not an agent's commit
    (datetime(2023, 6, 2, 12, 3, tzinfo=UTC), None, f'{{"commit_hash": "hook-{_RUN}"}}'),
    # outside the range on both sides
    (datetime(2023, 5, 31, 23, 59, tzinfo=UTC), EXEC, f'{{"sha": "early-{_RUN}"}}'),
    (UNTIL, EXEC, f'{{"sha": "late-{_RUN}"}}'),
]


@pytest.fixture
async def seeded(test_infrastructure: TestInfrastructure) -> AsyncGenerator[str, None]:
    import asyncpg

    from syn_adapters.events import AgentEventStore

    dsn = test_infrastructure.timescaledb_url
    store = AgentEventStore(dsn)
    await store.initialize()
    await store.close()
    pool = await asyncpg.create_pool(dsn)
    assert pool is not None
    try:
        async with pool.acquire() as conn:
            for at, execution_id, data in _ROWS:
                await conn.execute(
                    "INSERT INTO agent_events (time, event_type, session_id, execution_id, data) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb)",
                    at,
                    GIT_COMMIT,
                    SESSION,
                    execution_id,
                    data,
                )
            # a non-commit event in range: never a commit
            await conn.execute(
                "INSERT INTO agent_events (time, event_type, session_id, execution_id, data) "
                "VALUES ($1, $2, $3, $4, $5::jsonb)",
                SINCE + timedelta(hours=1),
                SESSION_STARTED,
                SESSION,
                EXEC,
                f'{{"sha": "not-a-commit-{_RUN}"}}',
            )
        yield dsn
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_events WHERE session_id = $1", SESSION)
        await pool.close()


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata", "America/Los_Angeles"])
async def test_one_row_per_agent_sha_on_its_first_utc_day(seeded: str, zone: str) -> None:
    import asyncpg

    sep = "&" if "?" in seeded else "?"
    pool = await asyncpg.create_pool(f"{seeded}{sep}timezone={zone}")
    assert pool is not None
    try:
        rows = await TimescaleCommitSightings(pool).sightings(SINCE, UNTIL)
    finally:
        await pool.close()

    mine = {s.sha: (s.execution_id, s.day) for s in rows if s.sha.endswith(_RUN)}
    assert mine == {
        f"v2-{_RUN}": (EXEC, date(2023, 6, 1)),
        f"top-{_RUN}": (EXEC, date(2023, 6, 2)),
        f"ctx-{_RUN}": (EXEC, date(2023, 6, 2)),
    }


PR_SESSION = f"shipprq-{_RUN}"
PR_REPO = f"Acme/api-{_RUN}"


async def _tool_call(
    conn: asyncpg.pool.PoolConnectionProxy,
    tool_use_id: str,
    command: str,
    output: str,
    at: datetime,
    execution_id: str | None = EXEC,
) -> None:
    for offset, event_type, payload in (
        (0, TOOL_EXECUTION_STARTED, {"input_preview": command}),
        (5, TOOL_EXECUTION_COMPLETED, {"output_preview": output}),
    ):
        await conn.execute(
            "INSERT INTO agent_events (time, event_type, session_id, execution_id, data) "
            "VALUES ($1, $2, $3, $4, $5::jsonb)",
            at + timedelta(seconds=offset),
            event_type,
            PR_SESSION,
            execution_id,
            json.dumps({"tool_name": "Bash", "tool_use_id": tool_use_id, **payload}),
        )


@pytest.fixture
async def seeded_prs(test_infrastructure: TestInfrastructure) -> AsyncGenerator[str, None]:
    import asyncpg

    from syn_adapters.events import AgentEventStore

    dsn = test_infrastructure.timescaledb_url
    store = AgentEventStore(dsn)
    await store.initialize()
    await store.close()
    pool = await asyncpg.create_pool(dsn)
    assert pool is not None
    url = f"https://github.com/{PR_REPO}/pull"
    at = datetime(2023, 6, 2, 23, 0, tzinfo=UTC)
    try:
        async with pool.acquire() as conn:
            # created by a run: counted, on 06-02 UTC
            await _tool_call(conn, "t1", '{"command": "gh pr create --fill"}', f"{url}/11\n", at)
            # the same PR viewed later: not a creation
            await _tool_call(conn, "t2", "gh pr view 11", f"{url}/11", at + timedelta(days=1))
            # created outside any execution: not a run's PR
            await _tool_call(conn, "t3", "gh pr create", f"{url}/12", at, execution_id=None)
            # merges: a run's PR (repo spelled in another case) and someone else's
            for number, when in ((11, at + timedelta(days=2)), (99, at)):
                await conn.execute(
                    "INSERT INTO agent_events (time, event_type, session_id, data) "
                    "VALUES ($1, $2, $3, $4::jsonb)",
                    when,
                    GITHUB_PULL_REQUEST_MERGED,
                    PR_SESSION,
                    json.dumps({"repository": PR_REPO.lower(), "number": number}),
                )
        yield dsn
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_events WHERE session_id = $1", PR_SESSION)
        await pool.close()


async def test_run_prs_and_merges(seeded_prs: str) -> None:
    import asyncpg

    pool = await asyncpg.create_pool(seeded_prs)
    assert pool is not None
    try:
        source = TimescalePullRequestSightings(pool)
        opened = await source.opened(SINCE, UNTIL)
        merged = await source.merged(SINCE, UNTIL)
    finally:
        await pool.close()

    mine = [p for p in opened if p.repository == PR_REPO]
    assert [(p.number, p.execution_id, p.day) for p in mine] == [(11, EXEC, date(2023, 6, 2))]
    merges = sorted((m.number, m.day) for m in merged if m.repository == PR_REPO.lower())
    assert merges == [(11, date(2023, 6, 4)), (99, date(2023, 6, 2))]
