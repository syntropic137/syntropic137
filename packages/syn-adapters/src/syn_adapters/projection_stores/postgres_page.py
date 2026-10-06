"""``page_in_sql`` for the Postgres projection store (E2, second pass).

The store half of :class:`syn_domain.projection_scan.ProjectionSqlPage`: one
list page - its rows, ``total``, the facet tally and ``excluded_undated`` -
from one statement over one snapshot, never a row per document into Python.

PARITY WITH ``paginate`` IS THE CONTRACT, so every SQL expression below
mirrors one Python expression, and is used only on rows where the two cannot
differ:

========================  ==============================================  ==========================================
``paginate`` reads        SQL writes                                      exact when
========================  ==============================================  ==========================================
``str(ts or "")`` order   ``COALESCE(doc->>ts, '') COLLATE "C" DESC``     ts is a JSON string or null/absent
stable sort tie-break     ``raw_ts DESC NULLS LAST, id`` (the old read)   always: the old read's own ORDER BY
``str(facet or "")``      ``COALESCE(doc->>facet, '')``                   facet is a JSON string or null/absent
``casefold`` substring    ``strpos(lower(x COLLATE "C"), needle)``        every searched string is ASCII
``fromisoformat``         :data:`_INSTANT` (a strict ISO 8601 subset)     the string matches that subset
========================  ==============================================  ==========================================

``COLLATE "C"`` is not decoration: the database collation (en_US.utf8 in the
shipped image) orders punctuation and case differently from Python's code
point order, which ``C`` on UTF-8 reproduces exactly.

Any row outside those conditions is UNRESOLVED. The first statement counts
them; if there are any, their fields are read, the domain decides them with
``paginate``'s own predicates (``decide``), and the statement runs again with
those decisions joined in - inside the same REPEATABLE READ snapshot, so the
second run sees exactly the rows the first did. Real data has none, so a list
request is one statement.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from syn_adapters.projection_stores.lean_documents import lean_source
from syn_adapters.projection_stores.postgres_query_builder import _SAFE_FIELD, _build_where_clause
from syn_domain.projection_scan import SqlPage, UnjudgedRow, WindowPlacement

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import asyncpg

    from syn_domain.pagination import ProjectionRecord
    from syn_domain.projection_scan import Decide, JsonValue, RowDecision, SqlPageRequest

#: The ISO 8601 strings Postgres parses exactly as ``datetime.fromisoformat``
#: does: calendar date, optional ``T``/space time to the minute, optional
#: seconds with up to six fractional digits, optional ``Z`` or ``±HH:MM``.
#: Every range is narrowed to what BOTH accept - hour 00-23 and second 00-59
#: (Postgres takes 24:00 and :60, Python refuses them), offsets to ±15:59 (the
#: furthest Postgres accepts; Python goes to ±23:59) - and ``[0-9]`` rather
#: than ``\d``, which a Unicode-aware regex engine widens to other scripts'
#: digits. A day the month does not have is checked separately, below. A
#: string outside this subset is not "undated": it is unresolved, and Python
#: decides it.
_ISO_SUBSET = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"([T ]([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9](\.[0-9]{1,6})?)?"
    r"(Z|[+-](0[0-9]|1[0-5]):[0-5][0-9])?)?$"
)


def _instant(text: str) -> str:
    """SQL for the instant ``text`` names when it is in :data:`_ISO_SUBSET`, else NULL.

    Nested CASEs, because only CASE guarantees evaluation order: the casts
    must never see a string the regex refused, and ``make_date`` must never
    see year 0000 (which Python also refuses). No offset reads as UTC, as
    ``coerce_datetime`` reads it.
    """
    days_in_month = (
        f"extract(day from make_date(left({text}, 4)::int, substr({text}, 6, 2)::int, 1)"
        " + interval '1 month' - interval '1 day')"
    )
    return (
        f"CASE WHEN {text} ~ '{_ISO_SUBSET}' AND left({text}, 4) <> '0000' THEN"
        f" CASE WHEN substr({text}, 9, 2)::int <= {days_in_month} THEN"
        f" CASE WHEN {text} ~ '(Z|[+-][0-9]{{2}}:[0-9]{{2}})$' THEN {text}::timestamptz"
        f" ELSE {text}::timestamp AT TIME ZONE 'UTC' END END END"
    )


def _field(name: str) -> str:
    # Interpolated, not bound: a JSON key cannot be a placeholder.
    if not _SAFE_FIELD.fullmatch(name):
        msg = f"unsafe list field {name!r}: expected a plain identifier"
        raise ValueError(msg)
    return name


def _kind(field: str) -> str:
    """``jsonb_typeof``, with an absent key reading as ``null`` (``.get`` gives None)."""
    return f"COALESCE(jsonb_typeof(doc->'{field}'), 'null')"


class _Params:
    def __init__(self, initial: list[object]) -> None:
        self.values = initial

    def add(self, value: object) -> str:
        self.values.append(value)
        return f"${len(self.values)}"


@dataclass(frozen=True)
class _Plan:
    """The parts both statements share: the candidate rows and how SQL judges them."""

    src: str
    """``WITH src AS (...)``: id, the lean document, the raw timestamp, its instant."""
    unresolved: str
    """True for a row SQL cannot judge exactly (see the module docstring)."""
    params: _Params
    """The filters' parameters; each statement appends only the ones it uses."""


def _plan(table_name: str, request: SqlPageRequest, *, lean_ready: bool) -> _Plan:
    shape = request.shape
    ts = _field(shape.timestamp_field)
    facet = _field(shape.facet_field)
    searched = [_field(f) for f in shape.search_fields]

    where_sql, filter_params = (
        _build_where_clause(dict(request.filters), start_idx=1) if request.filters else ("", [])
    )
    params = _Params(list(filter_params))
    windowed = request.after is not None or request.before is not None

    unresolved = [
        f"{_kind(ts)} NOT IN ('string', 'null')",
        f"{_kind(facet)} NOT IN ('string', 'null')",
    ]
    if windowed:
        unresolved.append(f"({_kind(ts)} = 'string' AND inst IS NULL)")
    if request.needle is not None:
        unresolved.extend(
            f"({_kind(f)} = 'string' AND octet_length(doc->>'{f}') <> char_length(doc->>'{f}'))"
            for f in searched
        )

    instant_column = f", {_instant(f"(doc->>'{ts}')")} AS inst" if windowed else ""
    src = (
        f"WITH src AS (SELECT id, doc, doc->>'{ts}' AS raw_ts{instant_column} FROM ("
        f"SELECT id, {lean_source(lean_ready=lean_ready)} AS doc FROM {table_name}{where_sql}"
        ") AS d)"
    )
    return _Plan(src=src, unresolved=" OR ".join(unresolved), params=params)


def _matched(request: SqlPageRequest, params: _Params) -> str:
    """``matches_search`` over the search fields, for a row that is not unresolved."""
    if request.needle is None:
        return "TRUE"
    if not request.needle.isascii():
        # A casefolded ASCII string holds no non-ASCII character, so only a
        # row with a non-ASCII field could match - and every such row is
        # unresolved, decided in Python.
        return "FALSE"
    needle = params.add(request.needle)
    return (
        " OR ".join(
            f"({_kind(f)} = 'string' AND strpos(lower((doc->>'{f}') COLLATE \"C\"), {needle}) > 0)"
            for f in request.shape.search_fields
        )
        or "FALSE"
    )


def _placement(request: SqlPageRequest, params: _Params) -> str:
    """``_window_verdict`` for a row that is not unresolved: its ts is null or in the subset."""
    if request.after is None and request.before is None:
        return str(WindowPlacement.INSIDE.value)
    after = params.add(request.after)
    before = params.add(request.before)
    return (
        f"CASE WHEN {_kind(request.shape.timestamp_field)} = 'null'"
        f" THEN {WindowPlacement.UNDATED.value}"
        f" WHEN ({after}::timestamptz IS NOT NULL AND inst < {after}::timestamptz)"
        f" OR ({before}::timestamptz IS NOT NULL AND inst > {before}::timestamptz)"
        f" THEN {WindowPlacement.OUTSIDE.value} ELSE {WindowPlacement.INSIDE.value} END"
    )


def build_page_query(
    table_name: str,
    request: SqlPageRequest,
    decisions: Sequence[RowDecision],
    *,
    lean_ready: bool,
) -> tuple[str, list[object]]:
    """The one statement: page rows (whole documents), total, facets, undated, unresolved."""
    plan = _plan(table_name, request, lean_ready=lean_ready)
    params = plan.params
    matched = _matched(request, params)
    placement = _placement(request, params)
    ts = request.shape.timestamp_field
    facet = request.shape.facet_field
    statuses = params.add(sorted(request.statuses) if request.statuses is not None else None)
    o_keys = params.add([d.key for d in decisions])
    o_matched = params.add([d.matched for d in decisions])
    o_facet = params.add([d.facet for d in decisions])
    o_place = params.add([int(d.placement) for d in decisions])
    o_sort = params.add([d.sort_key for d in decisions])
    limit = params.add(request.limit)
    offset = params.add(request.offset)
    inside = WindowPlacement.INSIDE.value
    outside = WindowPlacement.OUTSIDE.value
    undated = WindowPlacement.UNDATED.value

    # ``raw_ts DESC NULLS LAST, id`` is the order the old read handed
    # ``paginate``, whose sort is stable: it is what breaks ties between equal
    # sort keys, so it has to be this exact expression, in the database
    # collation, not the C one.
    input_order = "raw_ts DESC NULLS LAST, id"
    page_order = f'sort_key COLLATE "C" DESC, {input_order}'
    query = f"""{plan.src},
decided AS (
    SELECT * FROM unnest({o_keys}::text[], {o_matched}::bool[], {o_facet}::text[],
                         {o_place}::int[], {o_sort}::text[])
        AS o(id, matched, facet, placement, sort_key)
),
judged AS (
    SELECT s.id, s.raw_ts,
        (o.id IS NULL AND ({plan.unresolved})) AS unresolved,
        COALESCE(o.matched, {matched}) AS matched,
        COALESCE(o.facet, doc->>'{facet}', '') AS facet,
        COALESCE(o.placement, {placement}) AS placement,
        COALESCE(o.sort_key, doc->>'{ts}', '') AS sort_key
    FROM src s LEFT JOIN decided o ON o.id = s.id
),
kept AS (
    SELECT *, ({statuses}::text[] IS NULL OR facet = ANY({statuses}::text[])) AS selected
    FROM judged
    WHERE NOT unresolved AND matched AND placement <> {outside}
),
dated AS (SELECT * FROM kept WHERE placement = {inside}),
page AS (
    SELECT id, sort_key, raw_ts FROM dated WHERE selected
    ORDER BY {page_order} LIMIT {limit} OFFSET {offset}
)
SELECT
    (SELECT count(*) FROM judged WHERE unresolved) AS unresolved,
    (SELECT count(*) FROM dated WHERE selected) AS total,
    (SELECT count(*) FROM kept WHERE placement = {undated} AND selected) AS undated,
    (SELECT COALESCE(json_agg(json_build_array(facet, n) ORDER BY first_seen), '[]')
        FROM (SELECT facet, count(*) AS n, min(pos) AS first_seen
              FROM (SELECT facet, row_number() OVER (ORDER BY {input_order}) AS pos
                    FROM dated) AS positioned
              GROUP BY facet) AS tally) AS facets,
    (SELECT COALESCE(json_agg(t.data ORDER BY {page_order}), '[]')
        FROM page JOIN {table_name} t USING (id)) AS rows
"""
    return query, params.values


def build_unresolved_query(
    table_name: str, request: SqlPageRequest, *, lean_ready: bool
) -> tuple[str, list[object]]:
    """``[id, {field: value}]`` for every row ``build_page_query`` counts as unresolved."""
    plan = _plan(table_name, request, lean_ready=lean_ready)
    picked = ", ".join(f"'{_field(f)}', doc->'{f}'" for f in request.shape.fields)
    query = (
        f"{plan.src} SELECT COALESCE(json_agg(json_build_array(id, jsonb_build_object({picked}))),"
        f" '[]') FROM src WHERE {plan.unresolved}"
    )
    return query, plan.params.values


async def page_in_sql(
    pool: asyncpg.Pool,
    table_name: str,
    request: SqlPageRequest,
    decide: Decide,
    *,
    lean_ready: bool,
) -> SqlPage:
    """Run :func:`build_page_query`, deciding unresolved rows in Python if any exist."""
    async with (
        pool.acquire() as conn,
        conn.transaction(isolation="repeatable_read", readonly=True),
    ):
        query, params = build_page_query(table_name, request, [], lean_ready=lean_ready)
        row = await conn.fetchrow(query, *params)
        assert row is not None  # an aggregate-only SELECT always returns one row
        if row["unresolved"]:
            listing, list_params = build_unresolved_query(
                table_name, request, lean_ready=lean_ready
            )
            decisions = decide(_unjudged(await conn.fetchval(listing, *list_params)))
            query, params = build_page_query(table_name, request, decisions, lean_ready=lean_ready)
            row = await conn.fetchrow(query, *params)
            assert row is not None
            if row["unresolved"]:  # pragma: no cover - one snapshot, so impossible
                msg = f"{row['unresolved']} rows left undecided in {table_name}"
                raise AssertionError(msg)
    facets = [_pair(item) for item in _json_array(row["facets"])]
    rows = [_document(item) for item in _json_array(row["rows"])]
    return SqlPage(
        rows=rows,
        total=int(row["total"]),
        status_counts=dict(facets),
        excluded_undated=int(row["undated"]),
    )


def _json_array(value: object) -> list[JsonValue]:
    """A JSON array as asyncpg hands it back: text, unless a codec decoded it."""
    decoded: object = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        msg = f"expected a JSON array, got {type(decoded).__name__}"
        raise TypeError(msg)
    return cast("list[JsonValue]", decoded)


def _document(value: JsonValue) -> ProjectionRecord:
    if not isinstance(value, dict):
        msg = f"expected a JSON object, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _pair(value: JsonValue) -> tuple[str, int]:
    if not (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)):
        msg = f"expected [facet, count], got {value!r}"
        raise TypeError(msg)
    return str(value[0]), value[1]


def _unjudged(value: object) -> list[UnjudgedRow]:
    rows: list[UnjudgedRow] = []
    for item in _json_array(value):
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict)):
            msg = f"expected [id, {{field: value}}], got {item!r}"
            raise TypeError(msg)
        rows.append(UnjudgedRow(key=str(item[0]), values=item[1]))
    return rows


#: Projection -> the JSON fields its list page filters by equality, and so is
#: indexed on. ``(data->>'field')`` is the expression ``_build_where_clause``
#: writes, so the planner can use the index for it. Built CONCURRENTLY (below),
#: unlike ``postgres_helpers._FILTERED_FIELDS``, because these tables are
#: written by every session and every artifact: a plain CREATE INDEX on an
#: install with history would hold those writes for the length of the build.
LIST_FILTER_INDEXES: dict[str, tuple[str, ...]] = {
    "session_summaries": ("workflow_id", "execution_id", "parent_session_id"),
    "artifact_summaries": ("workflow_id", "execution_id", "session_id"),
}


#: How long a build may wait for the transactions CONCURRENTLY waits out. One
#: long transaction would otherwise hold the build - and its pool connection -
#: indefinitely; past this it fails, is logged, and the next start retries.
_INDEX_LOCK_TIMEOUT = "5s"


async def ensure_list_indexes(pool: asyncpg.Pool, projection: str, table_name: str) -> None:
    """Build the list filter indexes without ever blocking a writer or a reader.

    CONCURRENTLY, outside any transaction, so writers never wait for it; the
    store runs it as a background task, so no request does either. Its own
    waits are bounded by ``_INDEX_LOCK_TIMEOUT``. A concurrent build that died
    (timed out, cancelled) leaves an INVALID index that ``IF NOT EXISTS`` would
    skip forever, so an invalid one is dropped and rebuilt. A failure is logged
    and swallowed: the index makes a filtered page fast; without it the page
    scans and answers the same.
    """
    for field in LIST_FILTER_INDEXES.get(projection, ()):
        name = f"idx_{table_name}_list_{_field(field)}"
        try:
            async with pool.acquire() as conn:
                await conn.execute(f"SET lock_timeout = '{_INDEX_LOCK_TIMEOUT}'")
                valid = await conn.fetchval(
                    "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE c.relname = $1 AND c.relnamespace = current_schema()::regnamespace",
                    name,
                )
                if valid is True:
                    continue
                if valid is False:
                    await conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
                await conn.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                    f"ON {table_name} ((data->>'{field}'))"
                )
        except Exception:
            logger.warning(
                "Could not build %s; filtered list pages scan %s until the next start",
                name,
                table_name,
                exc_info=True,
            )
