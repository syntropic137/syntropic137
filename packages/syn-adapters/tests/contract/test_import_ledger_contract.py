"""One contract, two delegate import ledgers (#933, #1675, ADR-060).

The same assertions run against InMemoryImportLedger (unit) and the
PostgresImportLedger production wires instead (integration, against the test
stack's TimescaleDB on 15432, or ``TEST_DATABASE_URL``). The ledger is what
stops a re-import billing the same tokens twice, so the two properties that
matter are pinned here for both: the mark only rises, per bucket, and
``guard`` admits one importer per session at a time.

Every test uses its own execution id, so the Postgres leg can share the table
with other runs. The integration leg skips, never passes, when the database
does not answer.
"""

from __future__ import annotations

import asyncio
import os
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from syn_adapters.import_ledger import InMemoryImportLedger, PostgresImportLedger
from syn_domain.contexts.agent_sessions import BilledUsage
from syn_shared.testing import ENV_TEST_DATABASE_URL, get_test_timescaledb_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ImportLedger = InMemoryImportLedger | PostgresImportLedger


def _require(url: str) -> None:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "", parsed.port or 0), timeout=1):
            return
    except OSError:
        pytest.skip(f"no backend at {parsed.hostname}:{parsed.port}")


@pytest.fixture(
    params=[
        pytest.param("memory", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    ]
)
async def ledger(request: pytest.FixtureRequest) -> AsyncIterator[ImportLedger]:
    if request.param == "memory":
        yield InMemoryImportLedger()
    else:
        import asyncpg

        url = os.getenv(ENV_TEST_DATABASE_URL, get_test_timescaledb_url())
        _require(url)
        # Three: two concurrent guards each hold one, and a third is spare.
        pool = await asyncpg.create_pool(url, min_size=1, max_size=3)
        store = PostgresImportLedger(pool)
        await store.ensure_ready()
        yield store
        await pool.close()


def _execution() -> str:
    return f"contract-{uuid4().hex}"


async def test_an_unbilled_session_has_billed_nothing(ledger: ImportLedger) -> None:
    assert await ledger.already_billed(_execution(), "session") == BilledUsage()


async def test_a_recorded_mark_is_read_back_in_all_four_buckets(ledger: ImportLedger) -> None:
    execution = _execution()
    billed = BilledUsage(
        uncached_input_tokens=10, cache_read_tokens=20, cache_creation_tokens=30, output_tokens=40
    )
    await ledger.record_billed(execution, "session", billed)
    assert await ledger.already_billed(execution, "session") == billed


async def test_the_mark_only_rises_per_bucket(ledger: ImportLedger) -> None:
    """A stale import carrying older cumulative figures cannot lower the mark."""
    execution = _execution()
    await ledger.record_billed(
        execution,
        "session",
        BilledUsage(
            uncached_input_tokens=50, cache_read_tokens=5, cache_creation_tokens=50, output_tokens=5
        ),
    )
    await ledger.record_billed(
        execution,
        "session",
        BilledUsage(
            uncached_input_tokens=40, cache_read_tokens=9, cache_creation_tokens=10, output_tokens=6
        ),
    )
    assert await ledger.already_billed(execution, "session") == BilledUsage(
        uncached_input_tokens=50, cache_read_tokens=9, cache_creation_tokens=50, output_tokens=6
    )


async def test_marks_are_kept_per_execution_and_session(ledger: ImportLedger) -> None:
    first, second = _execution(), _execution()
    await ledger.record_billed(first, "a", BilledUsage(output_tokens=1))
    await ledger.record_billed(first, "b", BilledUsage(output_tokens=2))
    await ledger.record_billed(second, "a", BilledUsage(output_tokens=3))
    assert (await ledger.already_billed(first, "a")).output_tokens == 1
    assert (await ledger.already_billed(first, "b")).output_tokens == 2
    assert (await ledger.already_billed(second, "a")).output_tokens == 3


async def test_a_session_id_with_an_unstorable_codepoint_reads_back(ledger: ImportLedger) -> None:
    """The session id comes from the harness transcript: untrusted text (#1241)."""
    execution = _execution()
    await ledger.record_billed(execution, "sess\x00ion", BilledUsage(output_tokens=7))
    assert (await ledger.already_billed(execution, "sess\x00ion")).output_tokens == 7


async def test_reads_and_writes_work_inside_the_guard(ledger: ImportLedger) -> None:
    execution = _execution()
    async with ledger.guard(execution, "session"):
        await ledger.record_billed(execution, "session", BilledUsage(output_tokens=5))
        assert (await ledger.already_billed(execution, "session")).output_tokens == 5


async def test_the_guard_admits_one_importer_per_session_at_a_time(
    ledger: ImportLedger,
) -> None:
    execution = _execution()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with ledger.guard(execution, "session"):
            entered.set()
            await release.wait()

    async def contender() -> None:
        async with ledger.guard(execution, "session"):
            pass

    held = asyncio.create_task(holder())
    await entered.wait()
    waiting = asyncio.create_task(contender())
    await asyncio.sleep(0.3)
    assert not waiting.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(held, waiting), timeout=5)


async def test_the_guard_does_not_block_another_session(ledger: ImportLedger) -> None:
    execution = _execution()
    async with ledger.guard(execution, "a"):
        await asyncio.wait_for(_enter_and_leave(ledger, execution, "b"), timeout=5)


async def _enter_and_leave(ledger: ImportLedger, execution: str, session: str) -> None:
    async with ledger.guard(execution, session):
        pass
