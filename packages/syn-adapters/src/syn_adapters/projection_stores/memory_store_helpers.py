"""In-memory projection store helpers.

Extracted from memory_store.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore


def filter_values(wanted: object) -> tuple[object, ...]:
    """The values a filter accepts: one, or several meaning ANY of them.

    THE STORES MUST AGREE ON THIS, and for a while they did not (#1253). The
    Postgres store renders a collection as ``data->>'k' = ANY($n)``
    (``_condition`` in ``postgres_query_builder``) so that a caller asking
    "which executions belong to these twelve repos" gets one round trip
    instead of twelve, or instead of loading the table and filtering in
    Python. Seven insight handlers were moved onto that spelling via
    ``executions_by_repo``; this store was not taught it and kept comparing
    the collection ITSELF to a field. No field is ever equal to a list, so
    every one of those queries answered ``[]``.

    That failure is silent, which is what makes it worth a named function
    rather than an inline ``isinstance``: an empty result is a legal answer,
    so nothing raises. It surfaced as an ``IndexError`` three layers up, in a
    test indexing into a timeline that should not have been empty, and it
    reaches production wherever ADR-060 permits in-memory stores for real
    (offline mode), not just tests.

    Returned as a tuple, not matched here, because the two callers compare a
    single value differently and for a documented reason: ``query`` compares
    by Python equality, ``count`` by ``str()`` because Postgres compares the
    text that ``->>`` extracts. Cardinality is the decision they share; the
    comparison is not.
    """
    if isinstance(wanted, (list, tuple, set, frozenset)):
        return tuple(wanted)
    return (wanted,)


def apply_filters(
    results: list[dict[str, Any]], filters: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Keep results matching every key, where a value may be one or several.

    Several means ANY of them -- see `filter_values` for why the two stores
    have to agree about that.
    """
    if not filters:
        return results
    return [r for r in results if all(r.get(k) in filter_values(v) for k, v in filters.items())]


def apply_sorting(results: list[dict[str, Any]], order_by: str | None) -> list[dict[str, Any]]:
    """Sort results by field name, with optional '-' prefix for descending.

    Rows MISSING the sort field always go last, in both directions, matching
    the ``NULLS LAST`` this store's Postgres counterpart now emits. The two
    must agree: a test passing against the in-memory store and a production
    query behaving differently is worse than either bug alone.

    The previous implementation folded the is-None flag into the sort key and
    then reversed the whole tuple, so descending put missing values FIRST. That
    is issue #920 - artifacts predating ArtifactCreated v4 have a null
    ``created_at``, and ``-created_at`` ranked every one of them above every
    artifact created since, pushing the newest off the first page. Partitioning
    rather than key-folding is what keeps direction and null-placement
    independent.
    """
    if not order_by:
        return results
    descending = order_by.startswith("-")
    field_name = order_by.lstrip("-")
    present = [r for r in results if r.get(field_name) is not None]
    missing = [r for r in results if r.get(field_name) is None]
    present.sort(key=lambda x: x[field_name], reverse=descending)
    return present + missing


def apply_pagination(
    results: list[dict[str, Any]], offset: int, limit: int | None
) -> list[dict[str, Any]]:
    """Apply offset and limit to results."""
    if offset:
        results = results[offset:]
    if limit:
        results = results[:limit]
    return results


def clear_projection(store: InMemoryProjectionStore, projection: str) -> None:
    """Clear data for a specific projection."""
    if projection in store._data:
        del store._data[projection]
    if projection in store._state:
        del store._state[projection]
