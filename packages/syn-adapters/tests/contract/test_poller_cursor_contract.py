"""One contract, two poller cursor stores (#1675, ADR-060).

The same assertions run against InMemoryPollerCursorStore (unit) and the
PostgresPollerCursorStore production wires instead (integration, against the
test stack's TimescaleDB on 15432, or ``TEST_DATABASE_URL``).

The Postgres store keeps two columns, the ETag and ``last_event_id``, so a
cursor comes back with exactly that metadata and nothing else: no metadata
reads back as ``{"last_event_id": ""}``, and any other key is gone. A fake that
handed back the object it was given would let a poller rely on metadata that
does not survive a restart.

Every test uses its own source key, so the Postgres leg can share the table
with other runs. The integration leg skips, never passes, when the database
does not answer.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from event_sourcing.core.historical_poller import CursorData

from syn_adapters.github.poller_cursor_store import (
    InMemoryPollerCursorStore,
    PostgresPollerCursorStore,
)
from syn_shared.testing import ENV_TEST_DATABASE_URL, get_test_timescaledb_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

CursorStore = InMemoryPollerCursorStore | PostgresPollerCursorStore


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
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.integration,
                pytest.mark.may_skip(reason="skips when no Postgres answers", issue="#1984"),
            ],
        ),
    ]
)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[CursorStore]:
    if request.param == "memory":
        yield InMemoryPollerCursorStore()
    else:
        import asyncpg

        url = os.getenv(ENV_TEST_DATABASE_URL, get_test_timescaledb_url())
        _require(url)
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        yield PostgresPollerCursorStore(pool)
        await pool.close()


def _source() -> str:
    return f"contract/{uuid4().hex}"


async def test_an_unknown_source_has_no_cursor(store: CursorStore) -> None:
    assert await store.load(_source()) is None


async def test_a_saved_cursor_loads_back_with_its_etag_and_last_event_id(
    store: CursorStore,
) -> None:
    source = _source()
    await store.save(source, CursorData(value='W/"etag-1"', metadata={"last_event_id": "42"}))
    assert await store.load(source) == CursorData(
        value='W/"etag-1"', metadata={"last_event_id": "42"}
    )


async def test_saving_again_replaces_the_cursor(store: CursorStore) -> None:
    source = _source()
    await store.save(source, CursorData(value="old", metadata={"last_event_id": "1"}))
    await store.save(source, CursorData(value="new", metadata={"last_event_id": "2"}))
    assert await store.load(source) == CursorData(value="new", metadata={"last_event_id": "2"})


async def test_a_cursor_without_metadata_loads_back_with_an_empty_last_event_id(
    store: CursorStore,
) -> None:
    source = _source()
    await store.save(source, CursorData(value="etag"))
    assert await store.load(source) == CursorData(value="etag", metadata={"last_event_id": ""})


async def test_metadata_other_than_last_event_id_is_not_kept(store: CursorStore) -> None:
    source = _source()
    await store.save(source, CursorData(value="etag", metadata={"last_event_id": "7", "page": "3"}))
    assert await store.load(source) == CursorData(value="etag", metadata={"last_event_id": "7"})


async def test_load_all_returns_every_saved_source(store: CursorStore) -> None:
    first, second = _source(), _source()
    await store.save(first, CursorData(value="a", metadata={"last_event_id": "1"}))
    await store.save(second, CursorData(value="b"))
    loaded = await store.load_all()
    assert loaded[first] == CursorData(value="a", metadata={"last_event_id": "1"})
    assert loaded[second] == CursorData(value="b", metadata={"last_event_id": ""})
