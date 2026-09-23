"""A collection-valued filter means ANY of those values -- in EVERY store (#1253).

The heatmap work moved seven insight handlers off "load the whole
repo_correlation projection and filter it in Python" and onto a single
filtered read, `executions_by_repo`, which asks for several repos at once::

    store.query(REPO_CORRELATION, filters={"repo_full_name": [...]})

`postgres_query_builder._condition` was taught that a collection renders as
`= ANY($n)`. The in-memory store was not, and kept comparing the LIST to a
field. Nothing is ever equal to a list, so it answered `[]` to every one of
those queries -- and `[]` is a legal answer, so nothing raised at the store.
It surfaced three layers up as an `IndexError` in
`apps/syn-api/tests/test_running_duration_is_not_zero.py`, indexing into a
timeline that should not have been empty.

The reason the branch's own tests missed it is the point of this file's
location. They exercise `FakeProjectionStore` in
`syn_domain/contexts/organization/slices/conftest.py`, which WAS given the new
semantics in the same change. Fixing the double and not the adapter means
every handler test passes while the shipping store returns nothing, so these
tests drive the real `InMemoryProjectionStore` -- the one `syn_api` wires up,
and the one ADR-060 lets an offline deployment run for real -- and they drive
it through `executions_by_repo`, the consumer whose contract changed.
"""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_query_builder import build_query
from syn_domain.contexts.organization._shared.execution_correlation import executions_by_repo
from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

pytestmark = pytest.mark.unit

_CORRELATIONS = (
    ("exec-api-1", "acme/api"),
    ("exec-api-2", "acme/api"),
    ("exec-web-1", "acme/web"),
    ("exec-other", "other/thing"),
)


async def _seeded() -> InMemoryProjectionStore:
    store = InMemoryProjectionStore()
    for execution_id, repo in _CORRELATIONS:
        await store.save(
            REPO_CORRELATION,
            f"{execution_id}:{repo}",
            {"execution_id": execution_id, "repo_full_name": repo},
        )
    return store


@pytest.mark.anyio
async def test_a_system_spanning_several_repos_gets_all_of_them() -> None:
    """Two repos asked for in one read: the shape every system-scoped handler uses.

    A one-repo request would also have failed before the fix, but two is what
    `_get_execution_ids_for_system` actually sends and it cannot be satisfied
    by a store that only understands scalars.
    """
    store = await _seeded()

    found = await executions_by_repo(store, ["acme/api", "acme/web"])

    assert found == {
        "exec-api-1": "acme/api",
        "exec-api-2": "acme/api",
        "exec-web-1": "acme/web",
    }


@pytest.mark.anyio
async def test_repos_not_asked_for_stay_out() -> None:
    """ANY is not "everything" -- a filter that matched all rows would also go green above."""
    store = await _seeded()

    assert await executions_by_repo(store, ["acme/web"]) == {"exec-web-1": "acme/web"}


@pytest.mark.anyio
async def test_a_scalar_filter_still_means_exactly_that_value() -> None:
    """The widening must not cost the single-value case, which most callers use."""
    store = await _seeded()

    rows = await store.query(REPO_CORRELATION, filters={"repo_full_name": "acme/api"})

    assert {r["execution_id"] for r in rows} == {"exec-api-1", "exec-api-2"}


@pytest.mark.anyio
async def test_every_collection_spelling_is_accepted() -> None:
    """`executions_by_repo` gets a set from one caller and a list from another.

    `_condition` accepts list, tuple, set and frozenset; a store that handled
    only `list` would fail on exactly the system-scoped callers, which build
    `{r.full_name for r in repos}`.
    """
    store = await _seeded()
    wanted = ["acme/web"]

    for spelling in (list(wanted), tuple(wanted), set(wanted), frozenset(wanted)):
        rows = await store.query(REPO_CORRELATION, filters={"repo_full_name": spelling})
        assert [r["execution_id"] for r in rows] == ["exec-web-1"], spelling


@pytest.mark.anyio
async def test_an_empty_collection_matches_nothing_rather_than_everything() -> None:
    """`= ANY('{}')` is false for every row; the store must not read that as "no filter"."""
    store = await _seeded()

    assert await store.query(REPO_CORRELATION, filters={"repo_full_name": []}) == []


@pytest.mark.anyio
async def test_count_agrees_with_the_rows_it_counts() -> None:
    """`build_count_query` shares its WHERE builder with `build_query` so the two
    cannot drift. An in-memory count that understood only scalars would drift
    anyway, in the one store where nothing forces the two to agree."""
    store = await _seeded()
    filters = {"repo_full_name": ["acme/api", "acme/web"]}

    rows = await store.query(REPO_CORRELATION, filters=filters)

    assert await store.count(REPO_CORRELATION, filters=filters) == len(rows) == 3


def test_the_sql_side_states_the_same_contract() -> None:
    """Pins WHY the in-memory store behaves this way: it is matching Postgres.

    If the builder ever stopped emitting ANY, the in-memory semantics above
    would become the odd one out and this asserts someone finds out here.
    """
    sql, params = build_query(
        REPO_CORRELATION, filters={"repo_full_name": ["acme/api", "acme/web"]}
    )

    assert "data->>'repo_full_name' = ANY($1)" in sql
    assert params == [["acme/api", "acme/web"]]
