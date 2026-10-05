"""Parity: the Postgres ``page_keys`` answers what ``PageQuery.run`` answers (#967).

``PageQuery.run`` is ``paginate``, the definition of a list page. The store
answers the same query in one SQL statement; this seeds documents chosen to
be awkward for SQL - a timestamp with no offset, one with ``Z``, one that does
not parse, one absent, tied timestamps, a non-list ``tags``, a non-string
search field, mixed case - and compares the two answers whole for every query.
"""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore
from syn_domain.projection_page import PageQuery, StatusOf

pytestmark = pytest.mark.integration

PROJECTION = "page_query_parity"

DOCS: dict[str, dict[str, object]] = {
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
}

AFTER = datetime(2026, 10, 2, tzinfo=UTC)
BEFORE = datetime(2026, 10, 4, 12, tzinfo=UTC)
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
    PageQuery(status=TEXT, timestamp_field="at", contains_all={"tags": frozenset({"x", "y"})}),
    PageQuery(status=TEXT, timestamp_field="at", search="alpha", search_fields=("name",)),
    PageQuery(status=TEXT, timestamp_field="at", equals={"eval_id": "e1"}, limit=0),
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


def _keys_in_read_order(stored: list[dict[str, object]]) -> list[str]:
    """``get_all``'s order, which is the order ``paginate``'s stable sort breaks ties by."""
    names = {str(doc.get("name")): key for key, doc in DOCS.items()}
    return [names[str(doc.get("name"))] for doc in stored]
