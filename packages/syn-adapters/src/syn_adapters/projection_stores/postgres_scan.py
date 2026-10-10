"""``scan_fields``, ``count_by`` and ``get_many`` for the Postgres projection store (E2).

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
from syn_adapters.projection_stores.postgres_page_keys import instant_sql
from syn_adapters.projection_stores.postgres_query_builder import (
    _SAFE_FIELD,
    _build_order_clause,
    _build_where_clause,
)
from syn_domain.projection_newest import newest_per_group as decide_newest_per_group

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import asyncpg

    from syn_domain.pagination import ProjectionRecord
    from syn_domain.projection_count import GroupKey
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


def build_newest_per_group_query(
    table_name: str,
    *,
    group_field: str,
    timestamp_field: str,
    fields: Sequence[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    flag_field: str | None,
    lean_ready: bool,
) -> tuple[str, list[str]]:
    """``[id, group, timestamp, {field: value...}]`` per row Python must see.

    Postgres decides only what it reads exactly as Python does. Among rows
    whose timestamp ``syn_page_instant_v1`` resolves - the ISO subset both
    sides parse to the same instant - it keeps one per group: ``DISTINCT ON``
    the group, the parsed instant newest-first, then the id in code point
    order (``COLLATE "C"``, which is how Python compares ``str``). A string
    timestamp it does NOT resolve may still be one ``coerce_datetime`` reads
    (basic format ``20261002T090000Z``, seven fractional digits, a week date,
    an offset past +15:59), so every such row is returned as well, and
    :func:`newest_per_group` decides the group in Python with the domain's
    own rule. Exactly the domain's answer, in one statement; the extra rows
    are the rare malformed ones.

    A group is a JSON STRING, as the domain requires: ``->>`` would also turn
    a number or an object into text and give it a group. Read from the lean
    source, so a body nobody renders is never detoasted.
    """
    for field in (group_field, timestamp_field, *fields, *((flag_field,) if flag_field else ())):
        # Interpolated, not bound: a JSON key cannot be a placeholder.
        if not _SAFE_FIELD.fullmatch(field):
            msg = f"unsafe newest-per-group field {field!r}: expected a plain identifier"
            raise ValueError(msg)
    picked = ", ".join(f"'{field}', data->'{field}'" for field in fields)
    instant = instant_sql(timestamp_field)
    params: list[str] = []
    conditions: list[str] = []
    if filters:
        where_sql, params = _build_where_clause(dict(filters), start_idx=1)
        conditions.append(where_sql.removeprefix(" WHERE "))
    conditions.append(f"jsonb_typeof(data->'{group_field}') = 'string'")
    if flag_field:
        # Only a real JSON false is false (read_primary_flag); the CASE keeps
        # the boolean cast from ever seeing a string.
        conditions.append(
            f"CASE WHEN jsonb_typeof(data->'{flag_field}') = 'boolean' "
            f"THEN (data->'{flag_field}')::boolean ELSE true END"
        )
    query = (
        f"WITH candidates AS (SELECT id, data, {instant} AS at FROM ("
        f"SELECT id, {lean_source(lean_ready=lean_ready)} AS data FROM {table_name}"
        f") AS documents WHERE {' AND '.join(conditions)}), "
        f"resolved AS (SELECT DISTINCT ON (data->>'{group_field}') id, data FROM candidates "
        f"WHERE at IS NOT NULL "
        f"ORDER BY data->>'{group_field}', at DESC, id COLLATE \"C\"), "
        "unresolved AS (SELECT id, data FROM candidates "
        f"WHERE at IS NULL AND jsonb_typeof(data->'{timestamp_field}') = 'string') "
        "SELECT COALESCE(json_agg(json_build_array("
        f"id, data->>'{group_field}', data->'{timestamp_field}', jsonb_build_object({picked})"
        ")), '[]') AS newest FROM "
        "(SELECT id, data FROM resolved UNION ALL SELECT id, data FROM unresolved) AS rows"
    )
    return query, params


async def newest_per_group(
    pool: asyncpg.Pool,
    table_name: str,
    *,
    group_field: str,
    timestamp_field: str,
    fields: Sequence[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    flag_field: str | None,
    lean_ready: bool,
) -> dict[str, Mapping[str, JsonValue]]:
    """Run :func:`build_newest_per_group_query`; the domain picks each group's newest."""
    query, params = build_newest_per_group_query(
        table_name,
        group_field=group_field,
        timestamp_field=timestamp_field,
        fields=fields,
        filters=filters,
        flag_field=flag_field,
        lean_ready=lean_ready,
    )
    async with pool.acquire() as conn:
        newest = await conn.fetchval(query, *params)
    rows = json.loads(newest) if isinstance(newest, str) else newest
    if not isinstance(rows, list):
        msg = f"expected a JSON array from the query, got {type(rows).__name__}"
        raise TypeError(msg)
    picked: dict[str, Mapping[str, JsonValue]] = {}
    candidates: list[tuple[str, dict[str, JsonValue]]] = []
    for key, group, stamp, values in rows:
        picked[str(key)] = _json_object(values)
        candidates.append((str(key), {group_field: group, timestamp_field: stamp}))
    # The flag was applied in SQL; group and instant are judged here, by the
    # same function the in-memory store uses.
    winners = decide_newest_per_group(
        candidates, group_field=group_field, timestamp_field=timestamp_field
    )
    return {group: picked[key] for group, (key, _) in winners.items()}


def build_count_query(
    table_name: str,
    fields: Sequence[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    *,
    lean_ready: bool,
) -> tuple[str, list[str]]:
    """A row of ``(field text..., count)`` per group of matching documents (projection_count)."""
    if not fields:
        msg = "count_by needs at least one field to group by"
        raise ValueError(msg)
    for field in fields:
        if not _SAFE_FIELD.fullmatch(field):
            msg = f"unsafe group field {field!r}: expected a plain identifier"
            raise ValueError(msg)
    picked = ", ".join(f"data->>'{field}'" for field in fields)
    ordinals = ", ".join(str(position) for position in range(1, len(fields) + 1))
    params: list[str] = []
    where_sql = ""
    if filters:
        where_sql, params = _build_where_clause(dict(filters), start_idx=1)
    query = (
        f"SELECT {picked}, count(*) FROM ("
        f"SELECT id, {lean_source(lean_ready=lean_ready)} AS data "
        f"FROM {table_name}) AS documents{where_sql} GROUP BY {ordinals}"
    )
    return query, params


async def count_by(
    pool: asyncpg.Pool,
    table_name: str,
    fields: Sequence[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    *,
    lean_ready: bool,
) -> list[tuple[GroupKey, int]]:
    """Run :func:`build_count_query`; each group's field texts and its size."""
    query, params = build_count_query(table_name, fields, filters, lean_ready=lean_ready)
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    width = len(fields)
    return [(tuple(row[:width]), int(row[width])) for row in rows]


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
