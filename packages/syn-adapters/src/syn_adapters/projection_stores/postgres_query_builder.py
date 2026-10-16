"""PostgreSQL query builder for projection stores.

Extracted from postgres_helpers.py to reduce module cognitive complexity.
"""

import re
from typing import Any

from syn_adapters.projection_stores.json_text import filter_text

#: The comparison both stores share; see :mod:`.json_text`.
_serialize_filter_value = filter_text


def _condition(key: str, value: object, idx: int) -> tuple[str, object]:
    """One filter, as SQL and its bound parameter.

    A filter value may be one value or several, and several means ANY of them.
    Without that, a caller asking "which executions belong to these twelve
    repos" has only two moves: twelve round trips, or load the table and filter
    in Python - and the second is what every caller actually did (#1253). The
    predicate stays a single indexable comparison on ``data->>'key'`` either
    way, so one expression index serves both shapes.
    """
    if isinstance(value, (list, tuple, set, frozenset)):
        return f"data->>'{key}' = ANY(${idx})", [_serialize_filter_value(v) for v in value]
    return f"data->>'{key}' = ${idx}", _serialize_filter_value(value)


def _build_where_clause(
    filters: dict[str, Any],
    start_idx: int,
) -> tuple[str, list[Any]]:
    """Build a WHERE clause from filters, returning SQL fragment and params."""
    conditions: list[str] = []
    params: list[Any] = []
    for idx, (key, value) in enumerate(filters.items(), start=start_idx):
        condition, param = _condition(key, value, idx)
        conditions.append(condition)
        params.append(param)
    return " WHERE " + " AND ".join(conditions), params


_SAFE_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _build_order_clause(order_by: str | None) -> str:
    """Build an ORDER BY clause from an optional sort specifier.

    NULLS LAST ON BOTH DIRECTIONS, and it is not cosmetic. Postgres defaults
    ``DESC`` to ``NULLS FIRST``, so a projection where some rows predate a field
    puts every row MISSING that field ahead of every row that has it. With
    enough legacy rows the newest record is pushed off the first page entirely,
    which reads to a user as the write having failed.

    That is issue #920: artifacts created before ArtifactCreated v4 carry a null
    ``created_at``, and ``-created_at`` sorted them above every artifact created
    since. Rows that cannot answer the sort must not outrank rows that can.

    ``id`` LAST, as the tie-break (E2). Rows with an equal sort key used to come
    back in whatever order the sort left them, so which of two tied rows landed
    on a page could differ between two reads of the same data - including the
    full read and the field scan (syn_domain.projection_scan), which must agree
    row for row. The id is the primary key, so the order is now total.
    """
    if not order_by:
        return " ORDER BY updated_at DESC, id"
    descending = order_by.startswith("-")
    field = order_by[1:] if descending else order_by
    # The field is interpolated into SQL, not bound as a parameter -- a JSON key
    # cannot be a placeholder. No caller passes user input today, but this
    # function cannot see its callers, so it refuses anything that is not a
    # plain identifier rather than trusting them.
    if not _SAFE_FIELD.fullmatch(field):
        msg = f"unsafe order_by field {field!r}: expected a plain identifier"
        raise ValueError(msg)
    direction = "DESC" if descending else "ASC"
    return f" ORDER BY data->>'{field}' {direction} NULLS LAST, id"


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


def build_count_query(
    table_name: str,
    filters: dict[str, Any] | None = None,
) -> tuple[str, list[Any]]:
    """A COUNT(*) that filters exactly as `build_query` does.

    Shares `_build_where_clause` with the query it counts, so the two cannot
    drift into counting different things - which is the failure a hand-written
    second WHERE clause invites.
    """
    query = f"SELECT count(*) FROM {table_name}"
    params: list[Any] = []
    if filters:
        where_sql, params = _build_where_clause(filters, start_idx=1)
        query += where_sql
    return query, params
