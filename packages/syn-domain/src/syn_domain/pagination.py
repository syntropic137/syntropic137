"""One page of a list surface, computed from one filtered sequence.

``/executions`` and ``/sessions`` both answer three questions about the same
query: which rows are on this page, how many rows match in total, and how the
matching rows break down by status. Computing those from three separate passes
is what produced #1119 -- rows were filtered in Python while ``total`` came
from a store-level ``COUNT(*)``, so the two agreed only for as long as nobody
added a second filter dimension to one of them.

``paginate`` derives all three from a single traversal, so they cannot describe
different collections. Adding a filter means editing one predicate.

The predicate primitives (:func:`within_window`, :func:`matches_search`) live
here for the same reason: two list endpoints that each spell "is this row in
the time window" for themselves will eventually spell it differently.

This module is deliberately at the top level of ``syn_domain`` rather than
inside a bounded context -- ``orchestration`` and ``agent_sessions`` both need
it and it references neither. ``syn_domain.repository`` is the existing
precedent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Sequence


@dataclass(frozen=True)
class Page[T]:
    """The rows on this page, plus the two numbers describing what they came from."""

    rows: list[T]
    """This page only -- ``[offset : offset + limit]`` of the matching rows."""

    total: int
    """Rows matching every filter INCLUDING status, before slicing.

    This is the number a client pages against. It is the size of the collection
    the page was cut from, never the length of ``rows``.
    """

    status_counts: dict[str, int]
    """Matching rows tallied by status, ignoring the status filter itself.

    Status facets exist to tell an operator what they would get by selecting a
    different status, so they must be counted over everything else the query
    asked for and nothing more. Tallying after the status filter would leave
    every unselected chip reading zero.
    """

    @classmethod
    def unpaged(cls, rows: Sequence[T], *, status_of: Callable[[T], str]) -> Page[T]:
        """A page that is the whole collection: nothing was filtered or sliced."""
        counts: dict[str, int] = {}
        for row in rows:
            status = status_of(row)
            counts[status] = counts.get(status, 0) + 1
        return cls(rows=list(rows), total=len(rows), status_counts=counts)


def paginate[R, T](
    records: Iterable[R],
    *,
    base_predicate: Callable[[R], bool],
    status_of: Callable[[R], str],
    statuses: Collection[str] | None,
    sort_key: Callable[[R], str],
    to_row: Callable[[R], T],
    offset: int = 0,
    limit: int | None = None,
) -> Page[T]:
    """Filter, tally, sort and slice in one pass over ``records``.

    ``base_predicate`` covers every filter EXCEPT status. Status is expressed as
    ``statuses`` (a set of allowed values) rather than a second predicate so it
    cannot disagree with ``status_of``: the facet tally and the row filter read
    the same field by construction.

    Rows are ordered by ``sort_key`` descending. The key is a string because
    both list surfaces order by an ISO 8601 timestamp, and newest-first is
    the only order either offers -- so neither the key type nor the
    direction is a knob.

    ``limit=None`` means no cap.
    """
    allowed = set(statuses) if statuses else None
    counts: dict[str, int] = {}
    matched: list[R] = []

    for record in records:
        if not base_predicate(record):
            continue
        status = status_of(record)
        counts[status] = counts.get(status, 0) + 1
        if allowed is not None and status not in allowed:
            continue
        matched.append(record)

    matched.sort(key=sort_key, reverse=True)
    window = matched[offset : offset + limit] if limit is not None else matched[offset:]
    return Page(rows=[to_row(r) for r in window], total=len(matched), status_counts=counts)


def coerce_datetime(value: object) -> datetime | None:
    """The instant ``value`` names, as an aware UTC datetime; None if it names none.

    Accepts an ISO 8601 string or an existing datetime, and handles the
    trailing ``Z`` suffix (RFC 3339), which ``fromisoformat`` rejects before
    Python 3.11.

    A value carrying no offset is read as UTC. Every timestamp reaching this
    module is UTC already -- aggregates stamp ``datetime.now(UTC)`` -- so UTC
    is the only reading the stored data supports, and it is the reading
    ``reconciliation._started_before`` already applies to these same
    timestamps.

    That is deliberately the OPPOSITE of what the API does with a bound the
    caller sent (``syn_api.list_query.WindowBound`` refuses one with no
    offset), and the difference is who is there to ask. A bound is a question
    a person just typed, so an ambiguous one can be handed back. A row is a
    value the system wrote and is reading again years later; there is no one to
    hand it back to, and the alternatives are a 500 or dropping the row from a
    window it may well belong in.

    Normalising here is also what makes the comparison total. Python raises
    ``TypeError`` comparing an aware datetime with a naive one, so without it
    any caller -- not only the HTTP one behind the validated bound -- is one
    timezone-less value away from a 500 (#1183). After it there is one kind of
    datetime left and nothing downstream has to know which kind it was given.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def within_window(
    value: object,
    after: datetime | None,
    before: datetime | None,
) -> bool:
    """True if ``value`` is a timestamp inside the inclusive ``[after, before]``.

    A row with no parseable timestamp is OUTSIDE any bounded window and inside
    an unbounded one. It cannot be shown to be in the window asked for, so it is
    excluded from the rows, the total and the facet counts alike -- the three
    must agree about it or the count describes rows the query does not return
    (#920).

    Bounds and rows are compared as UTC instants, so this never raises on a
    timezone-less value on either side and no caller has to normalise before
    calling; :func:`coerce_datetime` owns that reading and explains why the
    API's answer for a bound is a stricter one.
    """
    if after is None and before is None:
        return True
    started = coerce_datetime(value)
    if started is None:
        return False
    lower = coerce_datetime(after)
    upper = coerce_datetime(before)
    if lower is not None and started < lower:
        return False
    return not (upper is not None and started > upper)


def matches_search(term: str | None, *fields: object) -> bool:
    """True if ``term`` appears case-insensitively in any of ``fields``.

    Free-text search has to happen wherever ``total`` is computed. Done on the
    client instead, the row count and the pagination label describe different
    sets the moment the search box is non-empty.
    """
    if not term:
        return True
    needle = term.casefold()
    return any(isinstance(f, str) and needle in f.casefold() for f in fields)
