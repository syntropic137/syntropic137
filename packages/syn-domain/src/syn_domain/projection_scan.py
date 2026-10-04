"""Page a projection by reading only the fields its filters need (E2).

``/executions``, ``/sessions`` and ``/artifacts`` each page a projection the
same way: load EVERY document, filter, tally and sort them in Python
(:func:`syn_domain.pagination.paginate`), then keep one page. The rows on the
page are a few dozen; the documents loaded to choose them are all of them.
Measured on the E2 latency gate's seed, ``/artifacts`` read 6,000 artifact
documents - each carrying its full markdown body - to show twenty titles, and
spent most of a 600ms request decompressing bodies no row on the page renders.

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

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.pagination import Page, ProjectionRecord, paginate

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
        filters: Mapping[str, str] | None = None,
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
    filters: Mapping[str, str] | None,
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
