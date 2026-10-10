"""A list page a projection store answers in its own query (#967).

:func:`syn_domain.projection_scan.paginate_projection` reads a few fields of
EVERY candidate document and filters, tallies and slices them in Python, so a
request's cost grows with the collection rather than with the page. That is
the wrong shape for the north star: at 1,000 concurrent executions the
executions list is a scan of all history on every dashboard refresh.

A :class:`PageQuery` declares the whole page instead - which documents match,
what a row's status and timestamp are, which page is wanted - in terms a store
can evaluate where the data lives. A store that implements
:class:`ProjectionPager` answers it in one statement: the page's keys, the
exact ``total``, the status facets and ``excluded_undated``. Only the page's
documents are then read whole.

:meth:`PageQuery.run` is the same question answered in Python, through
:func:`syn_domain.pagination.paginate`. It is the definition the store's
answer is held to (the Postgres parity test runs both), and the read used for
a store that cannot answer the query itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.pagination import Page, ProjectionRecord, matches_search, paginate

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from datetime import datetime

    from event_sourcing import ProjectionStore


@dataclass(frozen=True)
class StatusOf:
    """Where a document's status comes from.

    Either a text field read as-is (absent reads as ``""``), or a boolean flag
    named by two labels. Both are declared rather than given as a callable so
    a store can compute the same status in its own query.
    """

    field: str
    if_true: str | None = None
    if_false: str | None = None

    @classmethod
    def text(cls, name: str) -> StatusOf:
        return cls(field=name)

    @classmethod
    def flag(cls, name: str, *, if_true: str, if_false: str) -> StatusOf:
        return cls(field=name, if_true=if_true, if_false=if_false)

    def of(self, record: ProjectionRecord) -> str:
        value = record.get(self.field)
        if self.if_true is not None and self.if_false is not None:
            return self.if_true if value is True else self.if_false
        return str(value or "")


@dataclass(frozen=True)
class PageQuery:
    """One page of a projection, newest first by ``timestamp_field``.

    Matching: ``equals`` field-for-field, ``present`` (each field holds a
    value when ``True``, is absent or null when ``False``), ``contains_all``
    (each field is a JSON list holding every value given), and ``search`` as a
    case-insensitive substring of any ``search_fields``. ``statuses`` and the inclusive
    ``[after, before]`` window are the two dimensions ``paginate`` reports on.

    Rows sharing a timestamp are ordered by their key, ascending: immutable, so
    a row cannot move between pages when another one is updated. A store breaks
    the tie by its key column; ``run`` by ``key_field`` of the document, which
    names the field holding that key (none: the records' own order).
    """

    status: StatusOf
    timestamp_field: str
    equals: Mapping[str, str] = field(default_factory=dict)
    present: Mapping[str, bool] = field(default_factory=dict)
    contains_all: Mapping[str, frozenset[str]] = field(default_factory=dict)
    search: str | None = None
    search_fields: tuple[str, ...] = ()
    statuses: frozenset[str] | None = None
    after: datetime | None = None
    before: datetime | None = None
    offset: int = 0
    limit: int | None = None
    key_field: str | None = None

    def matches(self, record: ProjectionRecord) -> bool:
        """Whether ``record`` passes every filter except status and the window."""
        if any(record.get(name) != value for name, value in self.equals.items()):
            return False
        if any((record.get(name) is not None) != wanted for name, wanted in self.present.items()):
            return False
        for name, required in self.contains_all.items():
            stored = record.get(name)
            if required and not (isinstance(stored, list) and required.issubset(stored)):
                return False
        return matches_search(self.search, *(record.get(name) for name in self.search_fields))

    def run[R, T](
        self,
        records: Iterable[R],
        *,
        document_of: Callable[[R], ProjectionRecord],
        to_row: Callable[[R], T],
        key_of: Callable[[R], str] | None = None,
    ) -> Page[T]:
        """This query answered in Python: the definition a store is held to.

        ``key_of`` is each record's key, the timestamp tie-break; by default
        the document's ``key_field``.
        """
        if key_of is None and self.key_field is not None:
            key_of = _field_of(document_of, self.key_field)
        return paginate(
            records,
            base_predicate=lambda r: self.matches(document_of(r)),
            status_of=lambda r: self.status.of(document_of(r)),
            statuses=self.statuses,
            timestamp_of=lambda r: document_of(r).get(self.timestamp_field),
            after=self.after,
            before=self.before,
            to_row=to_row,
            offset=self.offset,
            limit=self.limit,
            key_of=key_of,
        )


def _field_of[R](document_of: Callable[[R], ProjectionRecord], name: str) -> Callable[[R], str]:
    """A record's ``name`` field as text, for a sort key."""
    return lambda record: str(document_of(record).get(name) or "")


@runtime_checkable
class ProjectionPager(Protocol):
    """A projection store that answers a :class:`PageQuery` in its own query."""

    async def page_keys(self, projection: str, query: PageQuery) -> Page[str]:
        """The keys on the page, with ``total``, facets and undated count exact."""
        ...

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        """The full documents stored under ``keys``, by key; absent keys are omitted."""
        ...


async def page_projection[T](
    store: ProjectionStore,
    projection: str,
    query: PageQuery,
    *,
    to_row: Callable[[ProjectionRecord], T],
) -> Page[T]:
    """One page of ``projection``; documents are read whole only for the page.

    A document deleted between the two reads is dropped from the page, which
    comes back one row short with ``total`` still counting it.
    """
    if not isinstance(store, ProjectionPager):
        return query.run(await store.get_all(projection), document_of=lambda r: r, to_row=to_row)
    keys = await store.page_keys(projection, query)
    documents = await store.get_many(projection, keys.rows) if keys.rows else {}
    return Page(
        rows=[to_row(documents[key]) for key in keys.rows if key in documents],
        total=keys.total,
        status_counts=keys.status_counts,
        excluded_undated=keys.excluded_undated,
    )
