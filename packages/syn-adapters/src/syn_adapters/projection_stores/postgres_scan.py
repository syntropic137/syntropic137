"""``scan_fields`` and ``get_many`` for the Postgres projection store (E2).

The store half of :mod:`syn_domain.projection_scan`: read a few fields of every
matching document, then whole documents for one page. Filters and order are
built by the SAME helpers ``query`` uses (``_build_where_clause``,
``_build_order_clause``), applied to a subquery that exposes the scan's source
document as ``data`` - so the two reads cannot disagree about which rows match
or in which order they come, and for a table with a lean column
(:mod:`lean_documents`) neither the filter nor the sort detoasts a body.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from syn_adapters.postgres_text import pg_safe
from syn_adapters.projection_stores.lean_documents import lean_source
from syn_adapters.projection_stores.postgres_query_builder import (
    _SAFE_FIELD,
    _build_order_clause,
    _build_where_clause,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import asyncpg

    from syn_domain.pagination import ProjectionRecord
    from syn_domain.projection_scan import JsonValue


def build_scan_query(
    table_name: str,
    fields: Sequence[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    order_by: str | None,
    *,
    lean_ready: bool,
) -> tuple[str, list[str]]:
    """One JSON array of ``[id, {field: value...}]`` per matching document, in order."""
    for field in fields:
        # Interpolated, not bound: a JSON key cannot be a placeholder.
        if not _SAFE_FIELD.fullmatch(field):
            msg = f"unsafe scan field {field!r}: expected a plain identifier"
            raise ValueError(msg)
    picked = ", ".join(f"'{field}', data->'{field}'" for field in fields)
    # One JSON array for the whole scan, decoded once on the Python side: a
    # row per document would cost a json.loads per document, which at a few
    # thousand documents is most of the request. The order is the aggregate's
    # own ORDER BY - the clause ``query`` writes - because the order of an
    # aggregate's input is otherwise unspecified.
    params: list[str] = []
    where_sql = ""
    if filters:
        where_sql, params = _build_where_clause(dict(filters), start_idx=1)
    query = (
        f"SELECT COALESCE(json_agg(json_build_array(id, jsonb_build_object({picked}))"
        f"{_build_order_clause(order_by)}), '[]') AS scanned FROM ("
        f"SELECT id, updated_at, {lean_source(lean_ready=lean_ready)} AS data "
        f"FROM {table_name}) AS documents{where_sql}"
    )
    return query, params


async def scan_fields(
    pool: asyncpg.Pool,
    table_name: str,
    fields: Sequence[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    order_by: str | None,
    *,
    lean_ready: bool,
) -> list[tuple[str, Mapping[str, JsonValue]]]:
    """Run :func:`build_scan_query`; each row's fields as JSON values, by key."""
    query, params = build_scan_query(table_name, fields, filters, order_by, lean_ready=lean_ready)
    async with pool.acquire() as conn:
        scanned = await conn.fetchval(query, *params)
    pairs = json.loads(scanned) if isinstance(scanned, str) else scanned
    if not isinstance(pairs, list):
        msg = f"expected a JSON array from the scan, got {type(pairs).__name__}"
        raise TypeError(msg)
    return [(str(key), values) for key, values in pairs]


async def get_many(
    pool: asyncpg.Pool, table_name: str, keys: Sequence[str]
) -> dict[str, ProjectionRecord]:
    """The whole documents stored under ``keys``, by key."""
    if not keys:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, data FROM {table_name} WHERE id = ANY($1::text[])",
            [pg_safe(key) for key in keys],
        )
    return {str(row["id"]): _json_object(row["data"]) for row in rows}


def _json_object(value: object) -> Mapping[str, JsonValue]:
    """A JSONB object as asyncpg hands it back: text, unless a codec decoded it."""
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        msg = f"expected a JSON object, got {type(decoded).__name__}"
        raise TypeError(msg)
    return decoded
