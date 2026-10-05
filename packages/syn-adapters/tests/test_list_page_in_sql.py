"""A list page computed in SQL is the page ``paginate`` computes, row for row (E2).

``PostgresProjectionStore.page_in_sql`` answers /sessions and /artifacts in one
statement. Its contract is parity with ``paginate`` over the old full read -
the rows, their order, ``total``, the facet tally (and its order) and
``excluded_undated``. The API parity test holds it to that on realistic data;
this holds it to it on hostile data, where Postgres and Python genuinely
disagree and the store must hand the row to Python instead of guessing:

- timestamps that are not ISO 8601 subset strings (basic format, hour 24,
  second 60, Feb 30, year 0000, an offset past +15:59, non-ASCII digits,
  words Postgres parses and Python does not), and non-string JSON values;
- equal sort keys, empty strings, nulls and absent keys, ids that the database
  collation and code point order sort differently;
- search terms and fields outside ASCII, where ``casefold`` and ``lower``
  part ways (sharp s, Kelvin sign, ligatures, dotted capital I);
- facet values that are not strings, and LIKE metacharacters in the term.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore
from syn_domain.projection_scan import JsonValue, ListShape, page_projection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.pagination import Page, ProjectionRecord

pytestmark = pytest.mark.integration

PROJECTION = "list_page_parity"
SHAPE = ListShape(timestamp_field="at", facet_field="kind", search_fields=("id", "name"))

TIMESTAMPS: list[JsonValue] = [
    "2026-10-01T10:00:00+00:00",
    "2026-10-01T10:00:00Z",
    "2026-10-01 10:00:00",
    "2026-10-01T10:00:00.5+00:00",
    "2026-10-01T10:00:00.123456-03:30",
    "2026-10-01T12:00:00+02:00",
    "2026-10-01T10:00",
    "2026-10-01",
    "2026-09-15T08:00:00+15:59",
    "2026-02-28T23:59:59+00:00",
    "2024-02-29T00:00:00+00:00",
    "",
    None,
    "20261001T100000",
    "2026-10-01T10",
    "2026-02-30T00:00:00+00:00",
    "2025-02-29T00:00:00",
    "2026-10-01T24:00:00",
    "2026-10-01T10:00:60",
    "2026-10-01T10:00:00+16:00",
    "2026-10-01T10:00:00+23:59",
    "0000-01-01T00:00:00",
    "٢٠٢٦-10-01",
    "2026-10-01t10:00:00",
    # Equal length, differing only in case or punctuation: the database
    # collation and code point order disagree about these.
    "2026-10-01T10:00:00",
    "2026-10-01 10:00:00",
    "2026-10-01_10:00:00",
    "2026-10-01-10:00:00",
    "2026-10-01T10:00:0a",
    "2026-10-01T10:00:0A",
    "yesterday",
    "epoch",
    "not a date",
    12345,
    1.5,
    True,
    False,
    0,
    {"a": 1},
    [1],
]
KINDS: list[JsonValue] = ["a", "b", "", None, "A", "ä", 5, True, False]
NAMES: list[JsonValue] = [
    "Hello",
    "HELLO world",
    "straße",
    "STRASSE",
    "Kelvin " + chr(0x212A),
    chr(0xFB01) + "le",
    "İstanbul",
    "naïve",
    "100% done_",
    123,
    None,
]
IDS = ["a1", "A1", "b", "_x", "-y", "B", "ä1", "a-1", "a_1", "z"]

SEARCHES = [None, "", "hello", "ss", "ẞ", "k", "fi", "i̇", "é", "%", "_", "A1"]
STATUSES: list[list[str] | None] = [None, ["a"], ["", "b"], ["5"], ["True"]]
BOUND = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
WINDOWS: list[tuple[datetime | None, datetime | None]] = [
    (None, None),
    (BOUND, None),
    (None, BOUND),
    (BOUND, BOUND + timedelta(hours=2)),
    (BOUND.replace(tzinfo=None), None),
]
SLICES = [(0, 4), (3, None), (0, None)]


@pytest.fixture
async def pool(test_infrastructure) -> AsyncIterator[asyncpg.Pool]:
    """A pool on a database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"list_page_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_url)
    await admin.execute(f'CREATE DATABASE "{name}"')
    parts = urlsplit(admin_url)
    created = await asyncpg.create_pool(urlunsplit(parts._replace(path=f"/{name}")))
    assert created is not None
    try:
        yield created
    finally:
        await created.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


class _QueryOnly:
    """The old read: only ``query``, so ``page_projection`` falls back to ``paginate``."""

    def __init__(self, store: PostgresProjectionStore) -> None:
        self._store = store


def _documents() -> list[dict[str, JsonValue]]:
    rng = random.Random(1580)
    docs: list[dict[str, JsonValue]] = []
    for n in range(240):
        doc: dict[str, JsonValue] = {
            "id": f"{IDS[n % len(IDS)]}-{n // len(IDS)}" if n % 13 else IDS[n % len(IDS)],
            "grp": ("g1", "g2")[n % 2],
        }
        # Absent keys as well as null ones: ``.get`` reads both as None.
        if n % 17:
            doc["at"] = rng.choice(TIMESTAMPS)
        if n % 19:
            doc["kind"] = rng.choice(KINDS)
        if n % 23:
            doc["name"] = rng.choice(NAMES)
        docs.append(doc)
    return docs


async def _page(
    store: object,
    pg: PostgresProjectionStore,
    *,
    filters: dict[str, str] | None,
    search: str | None,
    statuses: list[str] | None,
    window: tuple[datetime | None, datetime | None],
    offset: int,
    limit: int | None,
) -> Page[ProjectionRecord]:
    return await page_projection(
        store,
        PROJECTION,
        shape=SHAPE,
        filters=filters,
        search=search,
        statuses=statuses,
        after=window[0],
        before=window[1],
        full_read=lambda: pg.query(PROJECTION, filters=filters, order_by="-at"),
        to_row=lambda record: record,
        offset=offset,
        limit=limit,
    )


async def test_the_sql_page_is_the_page_paginate_cuts(pool: asyncpg.Pool) -> None:
    store = PostgresProjectionStore(pool)
    docs = _documents()
    for n, doc in enumerate(docs):
        await store.save(PROJECTION, f"{doc['id']}#{n}" if n % 7 == 0 else str(doc["id"]), doc)

    checked = 0
    undated_seen = False
    for filters in (None, {"grp": "g1"}):
        for search in SEARCHES:
            for statuses in STATUSES:
                for window in WINDOWS:
                    for offset, limit in SLICES:
                        kwargs = {
                            "filters": filters,
                            "search": search,
                            "statuses": statuses,
                            "window": window,
                            "offset": offset,
                            "limit": limit,
                        }
                        in_sql = await _page(store, store, **kwargs)  # type: ignore[arg-type]
                        in_python = await _page(_QueryOnly(store), store, **kwargs)  # type: ignore[arg-type]
                        assert in_sql.rows == in_python.rows, kwargs
                        assert in_sql.total == in_python.total, kwargs
                        assert list(in_sql.status_counts.items()) == list(
                            in_python.status_counts.items()
                        ), kwargs
                        assert in_sql.excluded_undated == in_python.excluded_undated, kwargs
                        undated_seen |= in_sql.excluded_undated > 0
                        checked += 1
    assert checked == 2 * len(SEARCHES) * len(STATUSES) * len(WINDOWS) * len(SLICES)
    # The hostile rows really were in play.
    assert undated_seen


async def test_an_ordinary_page_is_one_statement(pool: asyncpg.Pool) -> None:
    """Rows SQL can judge exactly never reach Python: ``decide`` is not called."""
    store = PostgresProjectionStore(pool)
    for n in range(30):
        stamp = (BOUND + timedelta(minutes=n % 7)).isoformat()
        await store.save(PROJECTION, f"r{n}", {"id": f"r{n}", "at": stamp, "kind": "a"})

    from syn_domain.projection_scan import SqlPageRequest

    def refuse(_rows: object) -> list[object]:
        raise AssertionError("an ordinary row was handed to Python")

    answer = await store.page_in_sql(
        PROJECTION,
        SqlPageRequest(
            shape=SHAPE,
            filters=None,
            needle="r1",
            statuses=None,
            after=BOUND,
            before=None,
            offset=0,
            limit=5,
        ),
        refuse,  # type: ignore[arg-type]
    )
    assert answer.total == 11
    assert len(answer.rows) == 5


async def test_the_list_filters_are_indexed_and_the_planner_uses_them(pool: asyncpg.Pool) -> None:
    from syn_adapters.projection_stores.postgres_page import LIST_FILTER_INDEXES

    store = PostgresProjectionStore(pool)
    for projection, fields in LIST_FILTER_INDEXES.items():
        await store.save(projection, "k", {"id": "k"})
        async with pool.acquire() as conn:
            for field in fields:
                valid = await conn.fetchval(
                    "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE c.relname = $1",
                    f"idx_{projection}_list_{field}",
                )
                assert valid is True, (projection, field)
            await conn.execute("SET enable_seqscan = off")
            plan = "\n".join(
                row[0]
                for row in await conn.fetch(
                    f"EXPLAIN SELECT id FROM {projection} WHERE data->>'execution_id' = 'e'"
                )
            )
            await conn.execute("RESET enable_seqscan")
        assert f"idx_{projection}_list_execution_id" in plan, plan
