"""The backfill replays Lane 2 history into the ledger once, strictly.

MARKED ``integration``: needs a real PostgreSQL with agent_events and its day
rollup trigger, which is how the backfill finds the sessions to visit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.events.shipped_ledger import backfill
from syn_domain.contexts.orchestration import ExecutionAttribution
from syn_shared.events import GIT_COMMIT, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

RUN = uuid4().hex[:8]
SESSION = f"shipbf-{RUN}"
EXEC = f"shipbfx-{RUN}"
REPO = f"acme/bf-{RUN}"
AT = datetime(2024, 3, 5, 10, tzinfo=UTC)


async def _attributions(ids: Sequence[str]) -> Mapping[str, ExecutionAttribution]:
    return {i: ExecutionAttribution(i, "wf-bf", "Backfill", (REPO,)) for i in ids if i == EXEC}


async def test_backfill_replays_commits_and_strict_prs_once(
    test_infrastructure: TestInfrastructure,
) -> None:
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    url = f"https://github.com/{REPO}/pull/5"
    rows = [
        (AT, GIT_COMMIT, {"git": {"sha": f"sha-{RUN}", "repo": REPO.split("/")[1]}}),
        (
            AT,
            TOOL_EXECUTION_STARTED,
            {"tool_use_id": "t1", "input_preview": json.dumps({"command": "gh pr create --fill"})},
        ),
        (
            AT + timedelta(seconds=2),
            TOOL_EXECUTION_COMPLETED,
            {"tool_use_id": "t1", "success": True, "output_preview": f"{url}\n"},
        ),
        # Cut preview: not trusted, never parsed into a PR.
        (
            AT,
            TOOL_EXECUTION_STARTED,
            {"tool_use_id": "t2", "input_preview": json.dumps({"command": "gh pr create --fill"})},
        ),
        (
            AT + timedelta(seconds=2),
            TOOL_EXECUTION_COMPLETED,
            {
                "tool_use_id": "t2",
                "success": True,
                "output_preview": "x" * 480 + f"\nhttps://github.com/{REPO}/pull/6",
            },
        ),
        # Failed create.
        (
            AT,
            TOOL_EXECUTION_STARTED,
            {"tool_use_id": "t3", "input_preview": json.dumps({"command": "gh pr create --fill"})},
        ),
        (
            AT + timedelta(seconds=2),
            TOOL_EXECUTION_COMPLETED,
            {
                "tool_use_id": "t3",
                "success": False,
                "output_preview": f"https://github.com/{REPO}/pull/7",
            },
        ),
    ]
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE shipped_daily, shipped_commits, shipped_pull_requests,"
                " github_pull_request_merges"
            )
            await conn.execute("UPDATE shipped_ledger_meta SET backfilled_at = NULL")
            for at, event_type, data in rows:
                await conn.execute(
                    "INSERT INTO agent_events (time, event_type, session_id, execution_id, data)"
                    " VALUES ($1, $2, $3, $4, $5::jsonb)",
                    at,
                    event_type,
                    SESSION,
                    EXEC,
                    json.dumps(data),
                )

        first = await backfill(pool, store.shipped_ledger, _attributions)
        again = await backfill(pool, store.shipped_ledger, _attributions)

        assert again == 0  # marked done: never re-read
        assert first >= 2
        day = await store.shipped_ledger.daily(AT.date(), AT.date(), "wf-bf")
        assert [(r.repository, r.commits, r.prs_opened) for r in day] == [(REPO, 1, 1)]
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_events WHERE session_id = $1", SESSION)
            await conn.execute("DELETE FROM agent_event_day_rollup WHERE session_id = $1", SESSION)
            await conn.execute(
                "TRUNCATE shipped_daily, shipped_commits, shipped_pull_requests,"
                " github_pull_request_merges"
            )
        await store.close()
