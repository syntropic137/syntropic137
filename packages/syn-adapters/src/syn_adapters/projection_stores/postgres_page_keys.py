"""``page_keys`` for the Postgres projection store (#967).

The store half of :mod:`syn_domain.projection_page`: one statement answers a
:class:`PageQuery` - the page's keys, the exact ``total``, the status facets
and ``excluded_undated`` - so nothing but the page leaves the database.

It must agree with :meth:`PageQuery.run`, which is ``paginate``:

- the window is judged on the parsed instant, and a value with no offset is
  read as UTC (``coerce_datetime``). A value that does not look like an ISO
  8601 timestamp is UNDATED rather than an error, as ``coerce_datetime``
  returns None for it;
- search is ``str.casefold``, which PostgreSQL 16 does not have: its
  ``lower()`` misses the full foldings (``ß`` -> ``ss``) and follows the
  database locale. The fold is done in SQL from a table built out of Python's
  own ``casefold``, so the two cannot drift;
- facets count dated, in-window rows ignoring the status filter; ``total`` and
  the undated count apply it;
- rows are ordered by the timestamp TEXT, newest first, with absent last.
"""

from __future__ import annotations

import json
from functools import cache
from typing import TYPE_CHECKING

import asyncpg

from syn_adapters.postgres_text import pg_safe
from syn_adapters.projection_stores.lean_documents import lean_source
from syn_adapters.projection_stores.postgres_query_builder import (
    _SAFE_FIELD,
    _build_where_clause,
)
from syn_domain.pagination import Page

if TYPE_CHECKING:
    from syn_domain.projection_page import PageQuery, StatusOf

#: What ``datetime.fromisoformat`` can read from a stored timestamp. Anything
#: else is undated rather than a cast error that would fail the whole request.
#: The ranges matter as well as the shape: PostgreSQL reads ``24:00`` and a
#: leap second ``:60``, which Python refuses. A day the month does not have
#: (``02-30``) passes any regex, so ``pg_input_is_valid`` judges that.
_HOUR = r"([01]\d|2[0-3])"
_SIXTY = r"[0-5]\d"
_OFFSET = rf"(Z|[+-]{_HOUR}:?{_SIXTY})"
_ISO_TIMESTAMP = (
    rf"^\d{{4}}-\d{{2}}-\d{{2}}([T ]{_HOUR}:{_SIXTY}(:{_SIXTY}(\.\d{{1,6}})?)?)?{_OFFSET}?$"
)
_HAS_OFFSET = rf"{_OFFSET}$"


@cache
def _folds() -> tuple[list[str], list[str]]:
    """Every character ``str.casefold`` changes, and what it changes it to.

    ``casefold`` works one character at a time, so folding a string is this
    table applied to each of its characters.
    """
    folded = [(c, c.casefold()) for c in map(chr, range(0x110000)) if c.casefold() != c]
    return [c for c, _ in folded], [f for _, f in folded]


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


#: The instant a stored timestamp names, or NULL when it names none. A function
#: rather than the expression inline so the window can be served by an index
#: (``postgres_page.LIST_WINDOW_INDEXES``), and an index expression must be
#: IMMUTABLE. The casts it guards are only STABLE in general, because they read
#: ``TimeZone`` and ``DateStyle``; here they are reached only by year-first ISO
#: text, which ``DateStyle`` cannot reorder, and the zone is either written in
#: the value or fixed to UTC, so the declaration is true of every input it sees.
#: plpgsql so it is never inlined: the planner must see the very call the index
#: was built on. The suffix is its version - change the body, change the name,
#: or an index built on the old body would answer for the new one.
INSTANT_FUNCTION = "syn_page_instant_v1"

INSTANT_FUNCTION_SQL = (
    f"CREATE OR REPLACE FUNCTION {INSTANT_FUNCTION}(stamp text) RETURNS timestamptz "
    "LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $fn$ BEGIN RETURN "
    f"CASE WHEN stamp ~ '{_ISO_TIMESTAMP}' THEN CASE WHEN stamp ~ '{_HAS_OFFSET}' "
    "THEN CASE WHEN pg_input_is_valid(stamp, 'timestamptz') THEN stamp::timestamptz END "
    "ELSE CASE WHEN pg_input_is_valid(stamp, 'timestamp') "
    "THEN stamp::timestamp AT TIME ZONE 'UTC' END END END; END $fn$"
)


_INSTANT_FUNCTION_EXISTS = (
    "SELECT EXISTS (SELECT 1 FROM pg_proc "
    "WHERE proname = $1 AND pronamespace = current_schema()::regnamespace)"
)


async def ensure_instant_function(pool: asyncpg.Pool) -> None:
    """Create :data:`INSTANT_FUNCTION` if it is missing. Every windowed page calls it.

    The catalogue is read first, so a restart that finds it in place writes
    nothing. A concurrent start creating it between the read and the write is
    the one way the write fails that is not a failure.
    """
    async with pool.acquire() as conn:
        if await conn.fetchval(_INSTANT_FUNCTION_EXISTS, INSTANT_FUNCTION):
            return
        try:
            await conn.execute(INSTANT_FUNCTION_SQL)
        except asyncpg.PostgresError:
            if not await conn.fetchval(_INSTANT_FUNCTION_EXISTS, INSTANT_FUNCTION):
                raise


def instant_sql(name: str) -> str:
    """The instant in field ``name``; the exact expression the window index is built on."""
    return f"{INSTANT_FUNCTION}(data->>'{_field(name)}')"


def _fold_sql(text: str, sources: str, targets: str) -> str:
    """``text.casefold()`` in SQL; ASCII, the usual case, skips the table."""
    upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return (
        f"CASE WHEN octet_length({text}) = char_length({text}) "
        f"THEN translate({text}, '{upper}', '{upper.lower()}') "
        f"ELSE (SELECT string_agg(COALESCE(f.target, c.ch), '' ORDER BY c.n) "
        f"FROM regexp_split_to_table({text}, '') WITH ORDINALITY AS c(ch, n) "
        f"LEFT JOIN unnest({sources}::text[], {targets}::text[]) AS f(source, target) "
        "ON f.source = c.ch) END"
    )


def _match_sql(query: PageQuery, params: _Params) -> str:
    conditions = ["TRUE"]
    if query.equals:
        where, values = _build_where_clause(dict(query.equals), start_idx=len(params.values) + 1)
        params.values.extend(values)
        conditions.append(where.removeprefix(" WHERE "))
    for name, wanted in query.present.items():
        # ``->>`` reads a JSON null as SQL NULL, as ``record.get`` reads it as None.
        conditions.append(f"data->>'{_field(name)}' IS {'NOT ' if wanted else ''}NULL")
    for name, required in query.contains_all.items():
        if required:
            tags = json.dumps(sorted(pg_safe(tag) for tag in required))
            conditions.append(f"data->'{_field(name)}' @> {params.add(tags)}::text::jsonb")
    if query.search and query.search_fields:
        needle = params.add(pg_safe(query.search).casefold())
        sources, targets = _folds()
        source_param, target_param = params.add(sources), params.add(targets)
        conditions.append(
            "("
            + " OR ".join(
                f"(jsonb_typeof(data->'{_field(name)}') = 'string' "
                f"AND strpos({_fold_sql(f"data->>'{name}'", source_param, target_param)}, "
                f"{needle}::text) > 0)"
                for name in query.search_fields
            )
            + ")"
        )
    return " AND ".join(conditions)


def _window_sql(query: PageQuery, params: _Params) -> tuple[str, str]:
    """The rows the window keeps, and how each kept row is judged.

    A windowed page keeps the rows inside it, which it reports, and the undated
    ones, which it counts. Nothing reads a row outside it, so the filter drops
    those in the scan, where an index on the instant can do it, instead of
    parsing every row's timestamp to judge it afterwards.
    """
    if query.after is None and query.before is None:
        return "TRUE", "'inside'"
    instant = instant_sql(query.timestamp_field)
    bounds = []
    if query.after is not None:
        bounds.append(f"{instant} >= {params.add(query.after)}::timestamptz")
    if query.before is not None:
        bounds.append(f"{instant} <= {params.add(query.before)}::timestamptz")
    kept = f"({instant} IS NULL OR ({' AND '.join(bounds)}))"
    return kept, f"CASE WHEN {instant} IS NULL THEN 'undated' ELSE 'inside' END"


def build_page_query(
    table_name: str, query: PageQuery, *, lean_ready: bool
) -> tuple[str, list[object]]:
    """One row: ``status_counts`` (JSON), ``total``, ``undated``, ``keys`` (JSON)."""
    params = _Params()
    stamp = _field(query.timestamp_field)
    match = _match_sql(query, params)
    window, verdict = _window_sql(query, params)
    selected = "TRUE"
    if query.statuses:
        selected = f"status = ANY({params.add(sorted(query.statuses))}::text[])"
    limit = "" if query.limit is None else f" LIMIT {int(query.limit)}"
    offset = f" OFFSET {int(query.offset)}" if query.offset else ""
    # "C" so the text compares by code point, as Python's ``str`` sort does.
    # Ties break on the key, never ``updated_at``: that moves when a row is
    # written, so a row could repeat on one page and vanish from the next.
    order = 'COALESCE(stamp, \'\') COLLATE "C" DESC, id COLLATE "C"'
    sql = (
        "WITH judged AS ("
        f"SELECT id, data->>'{stamp}' AS stamp, {_status_sql(query.status)} AS status, "
        f"{verdict} AS verdict "
        f"FROM (SELECT id, {lean_source(lean_ready=lean_ready)} AS data "
        f"FROM {table_name}) AS documents WHERE {match} AND {window}"
        ") "
        "SELECT "
        "(SELECT COALESCE(json_object_agg(status, n), '{}') FROM "
        "(SELECT status, count(*) AS n FROM judged WHERE verdict = 'inside' GROUP BY status) AS f"
        ") AS status_counts, "
        f"(SELECT count(*) FROM judged WHERE verdict = 'inside' AND {selected}) AS total, "
        f"(SELECT count(*) FROM judged WHERE verdict = 'undated' AND {selected}) AS undated, "
        f"(SELECT COALESCE(json_agg(id ORDER BY {order}), '[]') FROM "
        f"(SELECT id, stamp FROM judged WHERE verdict = 'inside' AND {selected} "
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
