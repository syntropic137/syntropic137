"""PostgreSQL query builder for projection stores.

Extracted from postgres_helpers.py to reduce module cognitive complexity.
"""

from typing import Any

# Type alias for filter values that can be serialized for JSONB queries
_FilterValue = str | int | bool | float


def _serialize_filter_value(value: _FilterValue) -> str:
    """Serialize a Python value to match PostgreSQL's JSONB ->> text extraction.

    JSONB ->> extracts booleans as 'true'/'false' (lowercase JSON literals),
    but Python's str(False) produces 'False'. This helper ensures values match.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_where_clause(
    filters: dict[str, Any],
    start_idx: int,
) -> tuple[str, list[Any]]:
    """Build a WHERE clause from filters, returning SQL fragment and params."""
    conditions: list[str] = []
    params: list[Any] = []
    for idx, (key, value) in enumerate(filters.items(), start=start_idx):
        conditions.append(f"data->>'{key}' = ${idx}")
        params.append(_serialize_filter_value(value))
    return " WHERE " + " AND ".join(conditions), params


def _build_order_clause(order_by: str | None) -> str:
    """Build an ORDER BY clause from an optional sort specifier."""
    if not order_by:
        return " ORDER BY updated_at DESC"
    if order_by.startswith("-"):
        return f" ORDER BY data->>'{order_by[1:]}' DESC"
    return f" ORDER BY data->>'{order_by}' ASC"


def build_query(
    table_name: str,
    filters: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """Build a parameterized query for projection records."""
    query = f"SELECT data FROM {table_name}"
    params: list[Any] = []

    if filters:
        where_sql, params = _build_where_clause(filters, start_idx=1)
        query += where_sql

    query += _build_order_clause(order_by)

    if limit is not None:
        query += f" LIMIT {limit}"
    if offset:
        query += f" OFFSET {offset}"

    return query, params
