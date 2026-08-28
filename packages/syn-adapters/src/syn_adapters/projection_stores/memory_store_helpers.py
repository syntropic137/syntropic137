"""In-memory projection store helpers.

Extracted from memory_store.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore


def apply_filters(
    results: list[dict[str, Any]], filters: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Filter results by matching all key-value pairs."""
    if not filters:
        return results
    return [r for r in results if all(r.get(k) == v for k, v in filters.items())]


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
