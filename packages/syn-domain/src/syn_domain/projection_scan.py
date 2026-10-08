"""Page a projection by reading only the fields its filters need (E2).

``/executions``, ``/sessions`` and ``/artifacts`` each page a projection the
same way: load EVERY document, filter, tally and sort them in Python
(:func:`syn_domain.pagination.paginate`), then keep one page. The rows on the
page are a few dozen; the documents loaded to choose them are all of them.
Measured on the E2 latency gate's seed, ``/artifacts`` read 6,000 artifact
documents - each carrying its full markdown body - to show twenty titles, and
spent most of a 470-660ms request shipping and JSON-decoding bodies no row on
the page renders.

:func:`paginate_projection` keeps ``paginate`` - the one definition of what
matches, how it is tallied and how it is ordered - and changes only what it is
fed. Two reads instead of one:

1. ``scan_fields``: for every candidate document, ONLY the fields the
   predicates read, so the filtering, the facets, ``total`` and the order are
   computed exactly as before over the same sequence, without the bodies.
2. ``get_many``: the full documents of the rows that landed on the page, so
   the rows handed back are exactly what ``to_row`` made of them before.

A store that cannot scan by field (the in-memory store, the test doubles) gets
the old single read, unchanged.

THE FIELD LIST IS CHECKED, NOT TRUSTED. A predicate that reads a field the
caller forgot to list would see ``None`` for every row and silently match
differently. :class:`ScannedRecord` raises instead, so that mistake fails the
first test that exercises the predicate rather than the first user who notices
a wrong count.

A ROW CAN VANISH BETWEEN THE TWO READS. A document deleted after the scan is
missing from ``get_many`` and is dropped from the page, which comes back one
row short with ``total`` still counting it - the same answer the single read
would have given a moment earlier, which is all two statements ever promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.pagination import (
    Page,
    ProjectionRecord,
    _window_verdict,  # the one definition of a row's place in a window
    _WindowVerdict,
    coerce_datetime,
    matches_search,
    paginate,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
    from datetime import datetime


#: A value as a projection document stores it: the document is JSON (JSONB in
#: Postgres), so this is every value a scanned field can hold.
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


@runtime_checkable
class ProjectionFieldScan(Protocol):
    """A projection store that can read selected fields of every document."""

    async def scan_fields(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, str | Sequence[str]] | None = None,
        order_by: str | None = None,
    ) -> list[tuple[str, Mapping[str, JsonValue]]]:
        """``(key, {field: value})`` per matching document, in ``order_by`` order.

        Same filter and order semantics as the store's ``query``; with no
        ``order_by``, the order of ``get_all``. Every listed field is present
        in each mapping, ``None`` where the document lacks it.
        """
        ...

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        """The full documents stored under ``keys``, by key; absent keys are omitted."""
        ...


class UndeclaredFieldError(LookupError):
    """A predicate read a field that the scan was not asked to fetch."""


class ScannedRecord(dict[str, JsonValue]):
    """The fields a scan fetched for one document; refuses to answer for any other.

    A ``dict`` so a read of a scanned field costs what a dict read costs: the
    scan builds one of these per document in the collection.
    """

    __slots__ = ("_fields",)

    def __init__(self, fields: frozenset[str], values: Mapping[str, JsonValue]) -> None:
        super().__init__({name: values.get(name) for name in fields})
        self._fields = fields

    def __missing__(self, key: str) -> JsonValue:
        raise UndeclaredFieldError(
            f"{key!r} is not one of the scanned fields {sorted(self._fields)}: "
            "add it to the projection's scan field list"
        )

    def get(self, key: str, default: JsonValue = None) -> JsonValue:  # type: ignore[override]  # refuses undeclared keys, unlike dict.get
        if key not in self._fields:
            self.__missing__(key)
        return super().get(key, default)


async def paginate_projection[T](
    store: object,
    projection: str,
    *,
    fields: Collection[str],
    filters: Mapping[str, str | Sequence[str]] | None,
    order_by: str | None,
    full_read: Callable[[], Awaitable[Iterable[ProjectionRecord]]],
    base_predicate: Callable[[ProjectionRecord], bool],
    status_of: Callable[[ProjectionRecord], str],
    statuses: Collection[str] | None,
    timestamp_of: Callable[[ProjectionRecord], object],
    after: datetime | None,
    before: datetime | None,
    to_row: Callable[[ProjectionRecord], T],
    offset: int,
    limit: int | None,
) -> Page[T]:
    """``paginate`` over ``projection``, reading whole documents only for the page.

    ``full_read`` is the single read this replaces, used verbatim when the
    store cannot scan by field. ``fields`` must name every field
    ``base_predicate``, ``status_of`` and ``timestamp_of`` read.
    """
    if not isinstance(store, ProjectionFieldScan):
        return paginate(
            await full_read(),
            base_predicate=base_predicate,
            status_of=status_of,
            statuses=statuses,
            timestamp_of=timestamp_of,
            after=after,
            before=before,
            to_row=to_row,
            offset=offset,
            limit=limit,
        )
    declared = frozenset(fields)
    scanned = [
        (key, ScannedRecord(declared, values))
        for key, values in await store.scan_fields(
            projection, sorted(declared), filters=filters, order_by=order_by
        )
    ]
    keys = paginate(
        scanned,
        base_predicate=lambda item: base_predicate(item[1]),
        status_of=lambda item: status_of(item[1]),
        statuses=statuses,
        timestamp_of=lambda item: timestamp_of(item[1]),
        after=after,
        before=before,
        to_row=lambda item: item[0],
        offset=offset,
        limit=limit,
    )
    documents = await store.get_many(projection, keys.rows) if keys.rows else {}
    return Page(
        rows=[to_row(documents[key]) for key in keys.rows if key in documents],
        total=keys.total,
        status_counts=keys.status_counts,
        excluded_undated=keys.excluded_undated,
    )


@runtime_checkable
class ProjectionKeyLookup(Protocol):
    """A projection store that reads many documents by primary key in one query."""

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        """The full documents stored under ``keys``, by key; absent keys are omitted."""
        ...


@runtime_checkable
class _ProjectionGet(Protocol):
    async def get(self, projection: str, key: str) -> ProjectionRecord | None: ...


async def read_by_keys(
    store: object, projection: str, keys: Sequence[str]
) -> dict[str, ProjectionRecord]:
    """Documents by primary key: one ``id = ANY(...)`` query where the store has
    ``get_many`` (Postgres), one keyed ``get`` per key otherwise (in-memory).

    Never a JSON-field filter: those have no index unless one is declared,
    and scan the whole table per call (#1545 review).
    """
    if not keys:
        return {}
    if isinstance(store, ProjectionKeyLookup):
        return await store.get_many(projection, keys)
    if not isinstance(store, _ProjectionGet):
        msg = f"{type(store).__name__} can read neither many keys nor one"
        raise TypeError(msg)
    found: dict[str, ProjectionRecord] = {}
    for key in keys:
        document = await store.get(projection, key)
        if document is not None:
            found[key] = document
    return found


# =============================================================================
# Paging in the store (E2, second pass): one SQL statement per list request.
# =============================================================================
#
# ``paginate_projection`` still reads every candidate row's filter fields into
# Python to filter, tally and order them. At 6,000 rows that is most of a
# list request on a CI runner (210-246ms for /sessions and /artifacts against
# a 200ms budget), and it grows with history. A store that can answer the
# whole page in SQL does: WHERE, ORDER BY, LIMIT/OFFSET, the total, the facet
# tally and the undated count, in one snapshot.
#
# THE ANSWER MUST BE THE ONE ``paginate`` GIVES, row for row. Postgres and
# Python disagree on a few things - case folding outside ASCII, which strings
# are ISO 8601 timestamps, how a non-string JSON value prints - so the store
# decides in SQL only the rows where the two provably agree, and hands every
# other row to :class:`ListShape`'s Python predicates (``decide``) and takes
# their verdict. On real data that set is empty and the request is one
# statement; it is never wrong, only slower, when it is not.


@dataclass(frozen=True)
class ListShape:
    """What a list surface filters, tallies, windows and orders by.

    The declarative form of the three callables ``paginate`` takes, so the
    store can write them as SQL and the domain can still evaluate them in
    Python (:meth:`base`, :meth:`facet_of`, :meth:`timestamp_of`) from the one
    definition.
    """

    timestamp_field: str
    """Windowed on, and the order: newest first, as ``paginate`` orders."""
    facet_field: str
    """``paginate``'s status dimension: tallied, and narrowed by ``statuses``."""
    search_fields: tuple[str, ...]
    """Matched case-insensitively against the search term."""

    @property
    def fields(self) -> tuple[str, ...]:
        """Every field the three predicates read."""
        return tuple(dict.fromkeys((*self.search_fields, self.facet_field, self.timestamp_field)))

    def base(self, search: str | None) -> Callable[[ProjectionRecord], bool]:
        def matches(record: ProjectionRecord) -> bool:
            return matches_search(search, *(record.get(f) for f in self.search_fields))

        return matches

    def facet_of(self, record: ProjectionRecord) -> str:
        return str(record.get(self.facet_field) or "")

    def timestamp_of(self, record: ProjectionRecord) -> object:
        return record.get(self.timestamp_field)


class WindowPlacement(IntEnum):
    """Where one row falls against the window, as the store encodes it."""

    INSIDE = 0
    OUTSIDE = 1
    UNDATED = 2


@dataclass(frozen=True)
class SqlPageRequest:
    """One page, described for a store that pages in SQL."""

    shape: ListShape
    filters: Mapping[str, str] | None
    needle: str | None
    """The search term casefolded, as ``matches_search`` compares it; None: no search."""
    statuses: frozenset[str] | None
    after: datetime | None
    before: datetime | None
    offset: int
    limit: int | None


@dataclass(frozen=True)
class RowDecision:
    """Python's answer for one row the store cannot judge exactly in SQL."""

    key: str
    matched: bool
    facet: str
    placement: WindowPlacement
    sort_key: str
    """``str(timestamp or "")``: the key ``paginate`` sorts by."""


@dataclass(frozen=True)
class SqlPage:
    """The store's answer: whole documents for the page, and the counts."""

    rows: list[ProjectionRecord]
    total: int
    status_counts: dict[str, int]
    excluded_undated: int


@dataclass(frozen=True)
class UnjudgedRow:
    """A row the store could not judge exactly: its key and the shape's fields."""

    key: str
    values: Mapping[str, JsonValue]
    """Every one of the shape's fields, ``None`` where the document lacks it."""


type Decide = Callable[[Sequence[UnjudgedRow]], list[RowDecision]]


@runtime_checkable
class ProjectionSqlPage(Protocol):
    """A projection store that answers a whole list page in SQL."""

    async def page_in_sql(
        self, projection: str, request: SqlPageRequest, decide: Decide
    ) -> SqlPage:
        """The page ``paginate`` would cut, computed in one snapshot.

        ``decide`` is called, inside that snapshot, with each row the store
        cannot judge exactly; the store must use its decisions verbatim.
        """
        ...


async def page_projection[T](
    store: object,
    projection: str,
    *,
    shape: ListShape,
    filters: Mapping[str, str] | None,
    search: str | None,
    statuses: Collection[str] | None,
    after: datetime | None,
    before: datetime | None,
    full_read: Callable[[], Awaitable[Iterable[ProjectionRecord]]],
    to_row: Callable[[ProjectionRecord], T],
    offset: int,
    limit: int | None,
) -> Page[T]:
    """``paginate`` over ``projection`` by ``shape``: in SQL where the store can.

    Falls back to :func:`paginate_projection` (the field scan, or the single
    full read) for a store that cannot page in SQL - the in-memory store and
    the test doubles - which is the same answer computed in Python.
    """
    base = shape.base(search)
    if isinstance(store, ProjectionSqlPage):
        declared = frozenset(shape.fields)

        def decide(rows: Sequence[UnjudgedRow]) -> list[RowDecision]:
            decisions: list[RowDecision] = []
            for row in rows:
                record = ScannedRecord(declared, row.values)
                stamp = shape.timestamp_of(record)
                decisions.append(
                    RowDecision(
                        key=row.key,
                        matched=base(record),
                        facet=shape.facet_of(record),
                        placement=_PLACEMENT[_window_verdict(stamp, after, before)],
                        sort_key=str(stamp or ""),
                    )
                )
            return decisions

        answer = await store.page_in_sql(
            projection,
            SqlPageRequest(
                shape=shape,
                filters=filters,
                needle=search.casefold() if search else None,
                statuses=frozenset(statuses) if statuses else None,
                # As ``_window_verdict`` reads them: aware, UTC if naive.
                after=coerce_datetime(after),
                before=coerce_datetime(before),
                offset=offset,
                limit=limit,
            ),
            decide,
        )
        return Page(
            rows=[to_row(record) for record in answer.rows],
            total=answer.total,
            status_counts=answer.status_counts,
            excluded_undated=answer.excluded_undated,
        )
    return await paginate_projection(
        store,
        projection,
        fields=shape.fields,
        filters=filters,
        order_by=f"-{shape.timestamp_field}",
        full_read=full_read,
        base_predicate=base,
        status_of=shape.facet_of,
        statuses=statuses,
        timestamp_of=shape.timestamp_of,
        after=after,
        before=before,
        to_row=to_row,
        offset=offset,
        limit=limit,
    )


# ``paginate``'s own verdict, so a row decided here is decided by the function
# that decides every row of the Python path - not by a second spelling of it.
_PLACEMENT: dict[_WindowVerdict, WindowPlacement] = {
    _WindowVerdict.INSIDE: WindowPlacement.INSIDE,
    _WindowVerdict.OUTSIDE: WindowPlacement.OUTSIDE,
    _WindowVerdict.UNDATED: WindowPlacement.UNDATED,
}
