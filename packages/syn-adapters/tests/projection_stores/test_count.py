"""A paginated endpoint must be able to report the COLLECTION size (#1119).

The defect: `total` was `len(page)`, so

    GET /executions?page_size=5    -> {"total": 5}
    GET /executions?page_size=100  -> {"total": 100}

against a projection holding 280 rows. `total` is the only field a client can
page on, and it always said "you have them all" - indistinguishable from a
genuinely small collection. It misled me into nearly filing a container-leak
bug from a partial page earlier the same day.

Counting by fetching everything and taking `len` would reintroduce the per-row
cost #1114 just removed, so the count belongs in the store.
"""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_query_builder import build_count_query

pytestmark = pytest.mark.unit

_PROJECTION = "workflow_executions"


async def _seeded() -> InMemoryProjectionStore:
    store = InMemoryProjectionStore()
    for i in range(7):
        await store.save(
            _PROJECTION,
            f"exec-{i}",
            {"workflow_execution_id": f"exec-{i}", "status": "running" if i < 3 else "completed"},
        )
    return store


@pytest.mark.anyio
async def test_count_is_the_collection_not_a_page() -> None:
    store = await _seeded()

    assert await store.count(_PROJECTION) == 7


@pytest.mark.anyio
async def test_count_applies_the_same_filter_the_query_does() -> None:
    """A count that ignored the filter would overstate every filtered page."""
    store = await _seeded()

    assert await store.count(_PROJECTION, {"status": "running"}) == 3
    assert await store.count(_PROJECTION, {"status": "completed"}) == 4


@pytest.mark.anyio
async def test_an_unknown_projection_counts_zero_rather_than_raising() -> None:
    store = InMemoryProjectionStore()

    assert await store.count("never-written") == 0


@pytest.mark.anyio
async def test_a_filter_matching_nothing_counts_zero() -> None:
    store = await _seeded()

    assert await store.count(_PROJECTION, {"status": "cancelled"}) == 0


def test_the_count_query_filters_through_the_same_where_builder() -> None:
    """The count and the query it describes must not build WHERE separately.

    Two hand-written clauses are two things that have to agree with nothing
    forcing them to, so this asserts the count carries the same parameterised
    predicate shape the row query does.
    """
    sql, params = build_count_query("projection_x", {"status": "running"})

    assert sql.startswith("SELECT count(*) FROM projection_x")
    assert "data->>'status' = $1" in sql
    assert params == ["running"]


def test_no_filters_means_no_where_clause() -> None:
    sql, params = build_count_query("projection_x", None)

    assert sql == "SELECT count(*) FROM projection_x"
    assert params == []
