"""Every ShippedLedger keeps the same promises: idempotent, order-free, replayable.

Run against the in-memory ledger (unit) and the SQL one (integration) with
the same cases, so the in-memory one is the readable statement of what the
SQL must do and cannot drift from it unnoticed.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.events.shipped_ledger_memory import InMemoryShippedLedger
from syn_domain.contexts.orchestration import (
    CommitShipped,
    PullRequestMerged,
    PullRequestOpened,
    ShippedDayRow,
    ShippedLedger,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
START, END = date(2026, 9, 1), date(2026, 10, 31)

type Fact = CommitShipped | PullRequestOpened | PullRequestMerged | Alias


def commit(sha: str, day: int = 0, repo: str = "acme/api", wf: str = "impl") -> CommitShipped:
    return CommitShipped(sha, f"e-{wf}", wf, wf.upper(), repo, T0 + timedelta(days=day))


def opened(
    number: int, day: int = 0, repo: str = "acme/api", wf: str = "impl"
) -> PullRequestOpened:
    url = f"https://github.com/{repo}/pull/{number}"
    return PullRequestOpened(repo, number, url, f"e-{wf}", wf, wf.upper(), T0 + timedelta(days=day))


def merged(
    number: int, day: int = 0, repo: str = "acme/api", repo_id: int | None = None
) -> PullRequestMerged:
    return PullRequestMerged(repo, number, T0 + timedelta(days=day), repo_id)


@dataclass(frozen=True)
class Alias:
    repository: str
    repository_id: int


async def apply(ledger: ShippedLedger, facts: Sequence[Fact]) -> None:
    for fact in facts:
        if isinstance(fact, CommitShipped):
            await ledger.record_commit(fact)
        elif isinstance(fact, PullRequestOpened):
            await ledger.record_pull_request_opened(fact)
        elif isinstance(fact, Alias):
            await ledger.record_repository_alias(fact.repository, fact.repository_id)
        else:
            await ledger.record_pull_request_merged(fact)


def counts(rows: Sequence[ShippedDayRow]) -> set[tuple[object, ...]]:
    return {
        (
            r.day,
            r.repository.lower(),
            r.workflow_id,
            r.commits,
            r.prs_opened,
            r.prs_merged,
            r.prs_opened_merged,
        )
        for r in rows
        if r.commits or r.prs_opened or r.prs_merged or r.prs_opened_merged
    }


FACTS: list[Fact] = [
    commit("a"),
    commit("b", 1),
    commit("c", 1, "acme/web", "docs"),
    # The same sha claimed by two executions: the earlier observation owns it.
    CommitShipped("d", "e-late", "late", "LATE", "acme/api", T0 + timedelta(days=2)),
    CommitShipped("d", "e-impl", "impl", "IMPL", "acme/api", T0 + timedelta(days=1)),
    opened(1),
    opened(2, 1, "ACME/api"),
    opened(3, 2, "acme/web", "docs"),
    merged(1, 3),
    merged(2, 3, "acme/API"),  # forge spelling differs in case
    merged(99, 3),  # a PR no run created
    # A PR opened in acme/old, merged after the repo moved to acme/new (id 77).
    opened(5, 0, "acme/old"),
    Alias("acme/old", 77),  # e.g. its own `opened` webhook, before the move
    merged(5, 4, "acme/new", 77),
]

EXPECTED = {
    (date(2026, 10, 1), "acme/api", "impl", 1, 1, 0, 1),
    (date(2026, 10, 2), "acme/api", "impl", 2, 1, 0, 1),
    (date(2026, 10, 2), "acme/web", "docs", 1, 0, 0, 0),
    (date(2026, 10, 3), "acme/web", "docs", 0, 1, 0, 0),
    (date(2026, 10, 4), "acme/api", "impl", 0, 0, 2, 0),
    (date(2026, 10, 1), "acme/old", "impl", 0, 1, 0, 1),
    (date(2026, 10, 5), "acme/old", "impl", 0, 0, 1, 0),
}


async def _checks(make: Callable[[], Awaitable[ShippedLedger]]) -> None:
    # 1. The facts in order.
    ledger = await make()
    await apply(ledger, FACTS)
    assert counts(await ledger.daily(START, END)) == EXPECTED

    # 2. Idempotent: every fact again, twice.
    await apply(ledger, FACTS + FACTS)
    assert counts(await ledger.daily(START, END)) == EXPECTED

    # 3. Order-free and replayable: shuffled, duplicated, on a fresh ledger.
    rng = random.Random(1857)
    for _ in range(12):
        ledger = await make()
        replay = FACTS * 2
        rng.shuffle(replay)
        await apply(ledger, replay)
        assert counts(await ledger.daily(START, END)) == EXPECTED

    # 4. The workflow filter and the date range.
    rows = await ledger.daily(date(2026, 10, 2), date(2026, 10, 3), "docs")
    assert counts(rows) == {r for r in EXPECTED if r[2] == "docs"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_in_memory_ledger_keeps_the_contract() -> None:
    async def make() -> ShippedLedger:
        return InMemoryShippedLedger()

    await _checks(make)


@pytest.fixture
async def postgres_ledgers(
    test_infrastructure: TestInfrastructure,
) -> AsyncIterator[Callable[[], Awaitable[ShippedLedger]]]:
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    assert store.pool is not None
    pool = store.pool

    async def make() -> ShippedLedger:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE shipped_daily, shipped_commits, shipped_pull_requests,"
                " github_pull_request_merges, github_repository_aliases"
            )
        return store.shipped_ledger

    try:
        yield make
    finally:
        await make()
        await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_ledger_keeps_the_contract(
    postgres_ledgers: Callable[[], Awaitable[ShippedLedger]],
) -> None:
    await _checks(postgres_ledgers)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_pr_and_its_merge_racing_are_counted_exactly_once(
    postgres_ledgers: Callable[[], Awaitable[ShippedLedger]],
) -> None:
    ledger = await postgres_ledgers()
    for number in range(1, 21):
        await asyncio.gather(
            ledger.record_pull_request_opened(opened(number)),
            ledger.record_pull_request_merged(merged(number, 1)),
            ledger.record_pull_request_merged(merged(number, 1)),
        )
    rows = await ledger.daily(START, END)
    assert sum(r.prs_opened for r in rows) == 20
    assert sum(r.prs_merged for r in rows) == 20
    assert sum(r.prs_opened_merged for r in rows) == 20


_FACT_TABLES = {
    "shipped_commits": "sha",
    "shipped_pull_requests": "repository_key, number",
    "github_pull_request_merges": "repository_key, number",
    "github_repository_aliases": "repository_key",
}


async def _fact_snapshot(conn: asyncpg.Connection) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every fact table, in key order."""
    return {
        table: [
            tuple(r.values()) for r in await conn.fetch(f"SELECT * FROM {table} ORDER BY {key}")
        ]
        for table, key in _FACT_TABLES.items()
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_rollup_version_change_rebuilds_from_facts_and_keeps_them(
    postgres_ledgers: Callable[[], Awaitable[ShippedLedger]],
    test_infrastructure: TestInfrastructure,
) -> None:
    """Facts are the record (merges have no other source): never reset, row for row."""
    import asyncpg

    from syn_adapters.events.shipped_ledger import ensure_shipped_ledger_schema

    ledger = await postgres_ledgers()
    await apply(ledger, FACTS)
    conn = await asyncpg.connect(test_infrastructure.timescaledb_url)
    try:
        before = await _fact_snapshot(conn)
        assert all(before.values())  # every fact table holds rows, aliases included
        await conn.execute("UPDATE shipped_daily SET commits = 999")  # a stale derivation
        await conn.execute("UPDATE shipped_ledger_meta SET rollup_version = 0")
        await ensure_shipped_ledger_schema(conn)
        await ensure_shipped_ledger_schema(conn)  # re-running applies nothing twice
        after = await _fact_snapshot(conn)
    finally:
        await conn.close()
    assert after == before
    assert counts(await ledger.daily(START, END)) == EXPECTED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_pre_release_schema_is_refused_with_the_drop_instruction(
    test_infrastructure: TestInfrastructure,
) -> None:
    """An earlier commit of #1857 created meta(version, ...): refused by name, not opaquely."""
    import asyncpg

    from syn_adapters.events.shipped_ledger import (
        PRE_RELEASE_SCHEMA_MESSAGE,
        PreReleaseShippedSchemaError,
        ensure_shipped_ledger_schema,
    )

    schema = f"shipped_prerelease_{uuid4().hex[:8]}"
    conn = await asyncpg.connect(test_infrastructure.timescaledb_url)
    try:
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(f"SET search_path TO {schema}")
        await conn.execute(
            "CREATE TABLE shipped_ledger_meta (id INT PRIMARY KEY DEFAULT 1,"
            " version INT NOT NULL, backfilled_at TIMESTAMPTZ)"
        )
        with pytest.raises(PreReleaseShippedSchemaError) as refused:
            await ensure_shipped_ledger_schema(conn)
        assert str(refused.value) == PRE_RELEASE_SCHEMA_MESSAGE
        assert "DROP TABLE IF EXISTS shipped_ledger_meta" in str(refused.value)
    finally:
        await conn.execute(f"DROP SCHEMA {schema} CASCADE")
        await conn.close()
