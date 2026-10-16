"""One contract, two projection stores (#1675, ADR-060).

The same assertions run against InMemoryProjectionStore (unit) and the
PostgresProjectionStore production wires instead (integration, against the
test stack's TimescaleDB on 15432, or ``TEST_DATABASE_URL``). Every read model
and every to-do-list processor sits on this store, and ``save_if`` is the
repository's only compare-and-set: a double whose ``save_if`` writes over a
row it was told not to would let every lost-update test pass while production
keeps the row, or the reverse.

Every test uses its own projection name, so the Postgres leg gets a table of
its own and drops it afterwards. The integration leg skips, never passes, when
the database does not answer.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from syn_adapters.projection_stores import InMemoryProjectionStore, PostgresProjectionStore
from syn_domain.storable_text import pg_safe
from syn_shared.testing import ENV_TEST_DATABASE_URL, get_test_timescaledb_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ProjectionStore = InMemoryProjectionStore | PostgresProjectionStore


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    attempt: int


def _require(url: str) -> None:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "", parsed.port or 0), timeout=1):
            return
    except OSError:
        pytest.skip(f"no backend at {parsed.hostname}:{parsed.port}")


@pytest.fixture
def projection() -> str:
    return f"contract_{uuid4().hex[:16]}"


@pytest.fixture(
    params=[
        pytest.param("memory", marks=pytest.mark.unit),
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.integration,
                pytest.mark.may_skip(reason="skips when no Postgres answers", issue="#1984"),
            ],
        ),
    ]
)
async def store(request: pytest.FixtureRequest, projection: str) -> AsyncIterator[ProjectionStore]:
    if request.param == "memory":
        yield InMemoryProjectionStore()
    else:
        import asyncpg

        url = os.getenv(ENV_TEST_DATABASE_URL, get_test_timescaledb_url())
        _require(url)
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        try:
            yield PostgresProjectionStore(pool)
        finally:
            await pool.execute(f'DROP TABLE IF EXISTS "{projection}"')
            await pool.close()


async def test_a_saved_record_is_read_back_by_its_key(
    store: ProjectionStore, projection: str
) -> None:
    await store.save(projection, "a", {"status": "running", "attempt": 1})
    assert await store.get(projection, "a") == {"status": "running", "attempt": 1}
    assert await store.get(projection, "missing") is None


async def test_saving_the_same_key_again_replaces_the_record(
    store: ProjectionStore, projection: str
) -> None:
    await store.save(projection, "a", {"status": "running", "attempt": 1})
    await store.save(projection, "a", {"status": "done"})
    assert await store.get(projection, "a") == {"status": "done"}
    assert await store.count(projection) == 1


async def test_get_many_returns_only_the_keys_that_exist(
    store: ProjectionStore, projection: str
) -> None:
    await store.save(projection, "a", {"status": "running"})
    await store.save(projection, "b", {"status": "done"})
    found = await store.get_many(projection, ["a", "b", "missing"])
    assert found == {"a": {"status": "running"}, "b": {"status": "done"}}


async def test_delete_removes_one_record_and_leaves_the_rest(
    store: ProjectionStore, projection: str
) -> None:
    await store.save(projection, "a", {"status": "running"})
    await store.save(projection, "b", {"status": "done"})
    await store.delete(projection, "a")
    await store.delete(projection, "missing")
    assert await store.get(projection, "a") is None
    assert [r["status"] for r in await store.get_all(projection)] == ["done"]


async def test_count_and_query_agree_on_an_equality_filter(
    store: ProjectionStore, projection: str
) -> None:
    for key, status in (("a", "running"), ("b", "done"), ("c", "running")):
        await store.save(projection, key, {"status": status, "attempt": 1})
    running = await store.query(projection, filters={"status": "running"})
    assert len(running) == 2
    assert await store.count(projection, {"status": "running"}) == 2
    assert await store.count(projection) == 3


async def test_save_if_with_no_expected_row_inserts_only_once(
    store: ProjectionStore, projection: str
) -> None:
    first = _Row(status="claimed", attempt=1)
    assert await store.save_if(projection, "a", first, expected=None) is True
    assert (
        await store.save_if(projection, "a", _Row(status="stolen", attempt=9), expected=None)
        is False
    )
    assert await store.get(projection, "a") == first.model_dump(mode="json")


async def test_save_if_writes_while_the_stored_row_still_matches(
    store: ProjectionStore, projection: str
) -> None:
    held = _Row(status="claimed", attempt=1)
    await store.save(projection, "a", held.model_dump(mode="json"))
    nxt = _Row(status="done", attempt=1)
    assert await store.save_if(projection, "a", nxt, expected=held) is True
    assert await store.get(projection, "a") == nxt.model_dump(mode="json")


async def test_save_if_refuses_a_stale_expected_row(
    store: ProjectionStore, projection: str
) -> None:
    """The lost update: two writers read attempt 1, one wins, the other must lose."""
    read = _Row(status="claimed", attempt=1)
    await store.save(projection, "a", read.model_dump(mode="json"))
    winner = _Row(status="claimed", attempt=2)
    assert await store.save_if(projection, "a", winner, expected=read) is True
    loser = _Row(status="done", attempt=2)
    assert await store.save_if(projection, "a", loser, expected=read) is False
    assert await store.get(projection, "a") == winner.model_dump(mode="json")


async def test_save_if_refuses_an_expected_row_that_is_not_there(
    store: ProjectionStore, projection: str
) -> None:
    expected = _Row(status="claimed", attempt=1)
    assert (
        await store.save_if(projection, "a", _Row(status="done", attempt=1), expected=expected)
        is False
    )
    assert await store.get(projection, "a") is None


async def test_a_raw_key_and_its_stored_spelling_address_one_record(
    store: ProjectionStore, projection: str
) -> None:
    """Postgres TEXT cannot hold NUL; both stores key a record by ``pg_safe`` (#1241).

    So the raw key and that spelling are one record for every operation: a
    read, a bulk read, a replacing write and a delete.
    """
    raw = "session\x00id"
    stored = pg_safe(raw)
    assert stored != raw
    await store.save(projection, raw, {"status": "running"})
    assert await store.get(projection, stored) == {"status": "running"}
    assert await store.get_many(projection, [raw, stored]) == {stored: {"status": "running"}}
    await store.save(projection, stored, {"status": "done"})
    assert await store.get(projection, raw) == {"status": "done"}
    assert await store.count(projection) == 1
    await store.delete(projection, raw)
    assert await store.get(projection, stored) is None
    assert await store.count(projection) == 0


@pytest.mark.parametrize(
    ("stored", "wanted", "other"),
    [
        ("running", "running", "done"),
        (1, "1", 2),
        (1, 1, 2),
        (True, "true", False),
        (False, False, True),
    ],
    ids=["string", "integer-as-text", "integer", "boolean-as-text", "boolean"],
)
async def test_query_and_count_compare_the_json_text_of_a_field(
    store: ProjectionStore, projection: str, stored: object, wanted: object, other: object
) -> None:
    """Postgres compares ``data->>'value'`` with the filter's text; so must the double.

    Exactly the matching record comes back, and count agrees with it.
    """
    await store.save(projection, "hit", {"value": stored})
    await store.save(projection, "miss", {"value": other})
    await store.save(projection, "null", {"value": None})
    await store.save(projection, "absent", {})
    assert await store.query(projection, filters={"value": wanted}) == [{"value": stored}]
    assert await store.count(projection, {"value": wanted}) == 1
