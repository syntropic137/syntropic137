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
    """Sort results by field name, with optional '-' prefix for descending."""
    if not order_by:
        return results
    descending = order_by.startswith("-")
    field_name = order_by.lstrip("-")
    return sorted(
        results,
        key=lambda x: (x.get(field_name) is None, x.get(field_name) or ""),
        reverse=descending,
    )


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
