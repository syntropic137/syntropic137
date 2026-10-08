"""Parity: the Postgres ``page_keys`` answers what ``PageQuery.run`` answers (#967).

``PageQuery.run`` is ``paginate``, the definition of a list page. The store
answers the same query in one SQL statement; this seeds documents chosen to
be awkward for SQL - a timestamp with no offset, one with ``Z``, one that does
not parse, ones shaped like a timestamp on no real day or hour, one absent,
tied timestamps, a non-list ``tags``, a non-string search field, mixed case, a
``ß`` only ``casefold`` matches - and compares the two answers whole for every
query.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import asyncpg
import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore
from syn_domain.projection_count import ProjectionGroupCount, count_by
from syn_domain.projection_page import PageQuery, StatusOf

if TYPE_CHECKING:
    from syn_domain.pagination import ProjectionRecord

pytestmark = pytest.mark.integration

PROJECTION = "page_query_parity"

# Raw store documents, malformed on purpose: ``ProjectionRecord`` is what
# ``PageQuery`` reads, and a model would refuse the shapes under test.
DOCS: dict[str, ProjectionRecord] = {
    "a": {
        "name": "Alpha",
        "status": "completed",
        "at": "2026-10-01T10:00:00+00:00",
        "tags": ["x", "y"],
        "eval_id": "e1",
        "archived": False,
    },
    "b": {
        "name": "beta",
        "status": "failed",
        "at": "2026-10-02T10:00:00Z",
        "tags": ["x"],
        "eval_id": "e1",
        "archived": True,
    },
    "c": {
        "name": "Gamma",
        "status": "completed",
        "at": "2026-10-03T10:00:00",
        "tags": [],
        "eval_id": "e2",
        "archived": False,
    },
    "d": {"name": "delta", "status": "running", "at": "not a date", "tags": ["x"], "eval_id": "e1"},
    "e": {"name": "Epsilon", "at": None, "tags": "x", "eval_id": None},
    # No eval_id at all: ``present`` reads it as the null above does.
    "k": {"name": "Kappa", "status": "completed", "at": "2026-10-03T12:00:00Z"},
    "f": {
        "name": 42,
        "status": "completed",
        "at": "2026-10-02T10:00:00Z",
        "tags": ["x", "y"],
        "eval_id": "e1",
        "archived": True,
    },
    "g": {
        "name": "ALPHA two",
        "status": "failed",
        "at": "2026-10-04T23:30:00-05:00",
        "tags": ["y"],
        "eval_id": "e2",
    },
    # ``casefold`` turns ß into ss; PostgreSQL's ``lower()`` does not.
    "h": {"name": "Straße", "status": "running", "at": "2026-10-03T08:00:00Z", "eval_id": "e2"},
    # Shaped like a timestamp, but no such day or hour: undated, not a cast error.
    "i": {"name": "Leap", "status": "failed", "at": "2026-02-30T10:00:00Z", "eval_id": "e1"},
    "j": {"name": "Midnight", "status": "failed", "at": "2026-10-02T24:00:00", "eval_id": "e1"},
}

AFTER = datetime(2026, 10, 2, tzinfo=UTC)
BEFORE = datetime(2026, 10, 4, 12, tzinfo=UTC)
#: Exactly the instants of "a" (after) and "g" (before, written at -05:00): the
#: window is inclusive at both ends, and an index range must keep both rows.
AT_A = datetime(2026, 10, 1, 10, tzinfo=UTC)
AT_G = datetime(2026, 10, 5, 4, 30, tzinfo=UTC)
TEXT = StatusOf.text("status")
FLAG = StatusOf.flag("archived", if_true="archived", if_false="active")

QUERIES = [
    PageQuery(status=TEXT, timestamp_field="at"),
    PageQuery(status=TEXT, timestamp_field="at", offset=2, limit=2),
    PageQuery(status=TEXT, timestamp_field="at", statuses=frozenset({"completed"})),
    PageQuery(status=TEXT, timestamp_field="at", after=AFTER),
    PageQuery(
        status=TEXT,
        timestamp_field="at",
        after=AFTER,
        before=BEFORE,
        statuses=frozenset({"failed"}),
    ),
    PageQuery(status=TEXT, timestamp_field="at", after=AT_A, before=AT_G),
    PageQuery(status=TEXT, timestamp_field="at", after=AT_G),
    PageQuery(status=TEXT, timestamp_field="at", before=AT_A),
    PageQuery(
        status=TEXT,
        timestamp_field="at",
        after=AT_A + timedelta(microseconds=1),
        before=AT_G - timedelta(microseconds=1),
    ),
    PageQuery(status=TEXT, timestamp_field="at", contains_all={"tags": frozenset({"x", "y"})}),
    PageQuery(status=TEXT, timestamp_field="at", search="alpha", search_fields=("name",)),
    PageQuery(status=TEXT, timestamp_field="at", search="STRASSE", search_fields=("name",)),
    PageQuery(
        status=TEXT, timestamp_field="at", after=AFTER, search="straß", search_fields=("name",)
    ),
    PageQuery(status=TEXT, timestamp_field="at", equals={"eval_id": "e1"}, limit=0),
    PageQuery(status=TEXT, timestamp_field="at", present={"eval_id": True}),
    PageQuery(status=TEXT, timestamp_field="at", present={"eval_id": False}),
    PageQuery(status=FLAG, timestamp_field="at", statuses=frozenset({"active"}), limit=3),
    PageQuery(
        status=FLAG,
        timestamp_field="at",
        before=BEFORE,
        search="A",
        search_fields=("name", "eval_id"),
    ),
]


@pytest.mark.parametrize(
    "query", QUERIES, ids=lambda q: f"{q.status.field}-{q.statuses}-{q.offset}-{q.limit}"
)
async def test_postgres_page_keys_answers_what_page_query_run_answers(
    e2_database: str, query: PageQuery
) -> None:
    pool = await asyncpg.create_pool(e2_database, min_size=1, max_size=2)
    try:
        store = PostgresProjectionStore(pool)
        # Written oldest key first, so ``updated_at`` cannot hide a tie the
        # timestamp sort leaves to it in the opposite direction.
        for key in reversed(DOCS):
            await store.save(PROJECTION, key, dict(DOCS[key]))
        stored = await store.get_all(PROJECTION)
        expected = query.run(
            [(key, DOCS[key]) for key in _keys_in_read_order(stored)],
            document_of=lambda kv: kv[1],
            to_row=lambda kv: kv[0],
        )

        assert await store.page_keys(PROJECTION, query) == expected
    finally:
        await pool.close()


def _keys_in_read_order(stored: list[ProjectionRecord]) -> list[str]:
    """``get_all``'s order, which is the order ``paginate``'s stable sort breaks ties by."""
    names = {str(doc.get("name")): key for key, doc in DOCS.items()}
    return [names[str(doc.get("name"))] for doc in stored]


@pytest.mark.parametrize(
    ("fields", "filters"),
    [
        (("eval_id", "status"), {"eval_id": ["e1", "e2"]}),
        (("eval_id", "status"), None),
        (("name",), {"eval_id": "e1"}),
    ],
)
async def test_postgres_count_by_answers_what_counting_the_documents_answers(
    e2_database: str,
    fields: tuple[str, ...],
    filters: dict[str, str | list[str]] | None,
) -> None:
    """The grouped SQL tally (#967) equals reading every document and counting it.

    The documents include a missing status, a null ``eval_id`` and a numeric
    ``name``, the values where ``->>`` and a Python read could disagree.
    """
    pool = await asyncpg.create_pool(e2_database, min_size=1, max_size=2)
    try:
        store = PostgresProjectionStore(pool)
        reference = InMemoryProjectionStore()
        for key, document in DOCS.items():
            await store.save(PROJECTION, key, dict(document))
            await reference.save(PROJECTION, key, dict(document))

        expected = await count_by(reference, PROJECTION, fields, filters=filters)

        assert isinstance(store, ProjectionGroupCount)
        assert dict(await store.count_by(PROJECTION, fields, filters=filters)) == expected
    finally:
        await pool.close()


async def test_the_execution_window_is_answered_from_its_index(e2_database: str) -> None:
    """The window is an index range scan on ``workflow_executions``, with the same answer.

    Seq scans are switched off so the planner takes the index whenever the
    query's expression IS the index's: if the two ever drift apart, it cannot,
    and the plan says so. A table this small would otherwise be scanned anyway.
    """
    from syn_adapters.projection_stores.postgres_page_keys import build_page_query

    projection = "workflow_executions"
    # The same awkward stamps, under the field this projection is windowed on.
    docs = {
        key: {("started_at" if f == "at" else f): v for f, v in doc.items()}
        for key, doc in DOCS.items()
    }
    query = PageQuery(status=TEXT, timestamp_field="started_at", after=AT_A, before=AT_G, limit=3)
    pool = await asyncpg.create_pool(e2_database, min_size=1, max_size=2)
    try:
        store = PostgresProjectionStore(pool)
        for key in reversed(docs):
            await store.save(projection, key, dict(docs[key]))
        # The store builds it in the background on first use of the table.
        await asyncio.gather(*store._index_builds)
        sql, params = build_page_query(projection, query, lean_ready=False)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SET LOCAL enable_seqscan = off")
            plan = "\n".join(row[0] for row in await conn.fetch(f"EXPLAIN {sql}", *params))
        stored = await store.get_all(projection)
        expected = query.run(
            [(key, docs[key]) for key in _keys_in_read_order(stored)],
            document_of=lambda kv: kv[1],
            to_row=lambda kv: kv[0],
        )

        assert f"idx_{projection}_window_started_at" in plan, plan
        assert await store.page_keys(projection, query) == expected
    finally:
        await pool.close()
