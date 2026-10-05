"""``page_keys`` for the Postgres projection store (#967).

The store half of :mod:`syn_domain.projection_page`: one statement answers a
:class:`PageQuery` - the page's keys, the exact ``total``, the status facets
and ``excluded_undated`` - so nothing but the page leaves the database.

It must agree with :meth:`PageQuery.run`, which is ``paginate``:

- the window is judged on the parsed instant, and a value with no offset is
  read as UTC (``coerce_datetime``). A value that does not look like an ISO
  8601 timestamp is UNDATED rather than an error, as ``coerce_datetime``
  returns None for it;
- facets count dated, in-window rows ignoring the status filter; ``total`` and
  the undated count apply it;
- rows are ordered by the timestamp TEXT, newest first, with absent last.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from syn_adapters.postgres_text import pg_safe
from syn_adapters.projection_stores.lean_documents import lean_source
from syn_adapters.projection_stores.postgres_query_builder import (
    _SAFE_FIELD,
    _build_where_clause,
)
from syn_domain.pagination import Page

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.projection_page import PageQuery, StatusOf

#: What ``datetime.fromisoformat`` can read from a stored timestamp. Anything
#: else is undated rather than a cast error that would fail the whole request.
_ISO_TIMESTAMP = r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?)?(Z|[+-]\d{2}:?\d{2})?$"
_HAS_OFFSET = r"(Z|[+-]\d{2}:?\d{2})$"


def _field(name: str) -> str:
    # Interpolated, not bound: a JSON key cannot be a placeholder.
    if not _SAFE_FIELD.fullmatch(name):
        msg = f"unsafe page field {name!r}: expected a plain identifier"
        raise ValueError(msg)
    return name


class _Params:
    def __init__(self) -> None:
        self.values: list[object] = []

    def add(self, value: object) -> str:
        self.values.append(value)
        return f"${len(self.values)}"


def _status_sql(status: StatusOf) -> str:
    name = _field(status.field)
    if status.if_true is not None and status.if_false is not None:
        # Labels are code, not input, but are still quoted as SQL literals.
        true_label = status.if_true.replace("'", "''")
        false_label = status.if_false.replace("'", "''")
        return (
            f"CASE WHEN data->'{name}' = 'true'::jsonb THEN '{true_label}' ELSE '{false_label}' END"
        )
    return f"COALESCE(data->>'{name}', '')"


def _instant_sql(name: str) -> str:
    text = f"data->>'{name}'"
    return (
        f"CASE WHEN {text} ~ '{_ISO_TIMESTAMP}' THEN CASE WHEN {text} ~ '{_HAS_OFFSET}' "
        f"THEN ({text})::timestamptz ELSE ({text})::timestamp AT TIME ZONE 'UTC' END END"
    )


def _match_sql(query: PageQuery, params: _Params) -> str:
    conditions = ["TRUE"]
    if query.equals:
        where, values = _build_where_clause(dict(query.equals), start_idx=len(params.values) + 1)
        params.values.extend(values)
        conditions.append(where.removeprefix(" WHERE "))
    for name, required in query.contains_all.items():
        if required:
            tags = json.dumps(sorted(pg_safe(tag) for tag in required))
            conditions.append(f"data->'{_field(name)}' @> {params.add(tags)}::text::jsonb")
    if query.search and query.search_fields:
        needle = params.add(pg_safe(query.search))
        conditions.append(
            "("
            + " OR ".join(
                f"(jsonb_typeof(data->'{_field(name)}') = 'string' "
                f"AND strpos(lower(data->>'{name}'), lower({needle}::text)) > 0)"
                for name in query.search_fields
            )
            + ")"
        )
    return " AND ".join(conditions)


def _verdict_sql(query: PageQuery, params: _Params) -> str:
    if query.after is None and query.before is None:
        return "'inside'"
    outside = []
    if query.after is not None:
        outside.append(f"instant < {params.add(query.after)}::timestamptz")
    if query.before is not None:
        outside.append(f"instant > {params.add(query.before)}::timestamptz")
    return (
        "CASE WHEN instant IS NULL THEN 'undated' "
        f"WHEN {' OR '.join(outside)} THEN 'outside' ELSE 'inside' END"
    )


def build_page_query(
    table_name: str, query: PageQuery, *, lean_ready: bool
) -> tuple[str, list[object]]:
    """One row: ``status_counts`` (JSON), ``total``, ``undated``, ``keys`` (JSON)."""
    params = _Params()
    stamp = _field(query.timestamp_field)
    match = _match_sql(query, params)
    verdict = _verdict_sql(query, params)
    selected = "TRUE"
    if query.statuses:
        selected = f"status = ANY({params.add(sorted(query.statuses))}::text[])"
    limit = "" if query.limit is None else f" LIMIT {int(query.limit)}"
    offset = f" OFFSET {int(query.offset)}" if query.offset else ""
    # "C" so the text compares by code point, as Python's ``str`` sort does.
    order = "COALESCE(stamp, '') COLLATE \"C\" DESC, updated_at DESC, id"
    sql = (
        "WITH matched AS ("
        f"SELECT id, updated_at, data->>'{stamp}' AS stamp, {_status_sql(query.status)} AS status, "
        f"{_instant_sql(stamp)} AS instant "
        f"FROM (SELECT id, updated_at, {lean_source(lean_ready=lean_ready)} AS data "
        f"FROM {table_name}) AS documents WHERE {match}"
        f"), judged AS (SELECT id, updated_at, stamp, status, {verdict} AS verdict FROM matched) "
        "SELECT "
        "(SELECT COALESCE(json_object_agg(status, n), '{}') FROM "
        "(SELECT status, count(*) AS n FROM judged WHERE verdict = 'inside' GROUP BY status) AS f"
        ") AS status_counts, "
        f"(SELECT count(*) FROM judged WHERE verdict = 'inside' AND {selected}) AS total, "
        f"(SELECT count(*) FROM judged WHERE verdict = 'undated' AND {selected}) AS undated, "
        f"(SELECT COALESCE(json_agg(id ORDER BY {order}), '[]') FROM "
        f"(SELECT id, updated_at, stamp FROM judged WHERE verdict = 'inside' AND {selected} "
        f"ORDER BY {order}{limit}{offset}) AS p) AS keys"
    )
    return sql, params.values


async def page_keys(
    pool: asyncpg.Pool, table_name: str, query: PageQuery, *, lean_ready: bool
) -> Page[str]:
    """Run :func:`build_page_query` and read its one row back as a page of keys."""
    sql, params = build_page_query(table_name, query, lean_ready=lean_ready)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    if row is None:
        msg = "page query returned no row"
        raise RuntimeError(msg)
    counts = _json(row["status_counts"])
    keys = _json(row["keys"])
    if not isinstance(counts, dict) or not isinstance(keys, list):
        msg = "page query returned malformed facets or keys"
        raise TypeError(msg)
    return Page(
        rows=[str(key) for key in keys],
        total=int(row["total"]),
        status_counts={str(status): int(n) for status, n in counts.items()},
        excluded_undated=int(row["undated"]),
    )


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value
