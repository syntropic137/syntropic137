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
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

#: One row as a projection store hands it back: JSON, so its values are
#: whatever the event carried.
#:
#: Named here because every caller of :func:`paginate` writes a predicate over
#: this shape and they were each spelling it out, which is one erased
#: annotation per list surface rather than one for the concept. It is still
#: erased - a record IS heterogeneous at this layer - so the fix, when the
#: projections gain typed read models, is one edit here.
type ProjectionRecord = Mapping[str, object]


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

    excluded_undated: int = 0
    """Rows dropped because their timestamp could not be read, not because it
    was out of range.

    ``total`` alone cannot distinguish "older than the window" from "carries no
    date at all", and a quarter of the artifact corpus is the second (#1215).
    A reader narrowing a window saw an unexplained gap and no way to tell which
    of the two it was; this is the number that tells them.

    Counted over the same filters as ``total``, so the two are directly
    comparable: these are rows that matched everything the query asked for and
    were dropped ONLY because the window could not be evaluated against them.
    Zero whenever the query gave no bounds -- an unbounded window evaluates
    every row, including the undated ones, which it returns.

    This is deliberately NOT "include the undated rows anyway". A 24-hour query
    that returns rows of unknown age is a different lie, not a fix.
    """

    @classmethod
    def unpaged(cls, rows: Sequence[T], *, status_of: Callable[[T], str]) -> Page[T]:
        """A page that is the whole collection: nothing was filtered or sliced.

        ``excluded_undated`` is 0 because nothing was excluded: with no window
        there is no row this page could not place in time.
        """
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
    timestamp_of: Callable[[R], object],
    after: datetime | None = None,
    before: datetime | None = None,
    to_row: Callable[[R], T],
    offset: int = 0,
    limit: int | None = None,
) -> Page[T]:
    """Filter, tally, sort and slice in one pass over ``records``.

    ``base_predicate`` covers every filter EXCEPT status and the time window.
    Both of those are dimensions of this function rather than conjuncts the
    caller folds into its predicate, and for the same reason: a boolean tells
    ``paginate`` only THAT a row was dropped, so anything it must report about
    WHY has to be decided here.

    Status is expressed as ``statuses`` (a set of allowed values) so it cannot
    disagree with ``status_of``: the facet tally and the row filter read the
    same field by construction.

    The window is expressed as ``timestamp_of`` plus the bounds so the two
    reasons a row can fail it stay distinguishable. Folded into
    ``base_predicate``, "outside the window" and "carries no date the window
    could be evaluated against" arrive as the same ``False``, and a quarter of
    the artifact corpus vanished into that gap with nothing in the response
    saying so (#1215). Here they are told apart and the second is counted into
    ``Page.excluded_undated``.

    Rows are ordered by ``timestamp_of`` descending -- the same field the window
    is applied to, which is what makes it impossible to bound one field while
    sorting by another. It is compared as a string because every list surface
    stores an ISO 8601 timestamp, and newest-first is the only order any of
    them offers, so neither the key nor the direction is a knob.

    ``limit=None`` means no cap.
    """
    allowed = set(statuses) if statuses else None
    counts: dict[str, int] = {}
    matched: list[R] = []
    undated = 0

    for record in records:
        if not base_predicate(record):
            continue
        verdict = _window_verdict(timestamp_of(record), after, before)
        if verdict is _WindowVerdict.OUTSIDE:
            continue
        status = status_of(record)
        selected = _status_is_selected(status, allowed)
        if verdict is _WindowVerdict.UNDATED:
            # Not tallied into the facets: a facet says what selecting that
            # option WOULD return, and selecting it would not return this row.
            # Counted against the same filters as ``total``, status included,
            # so the two numbers describe the same query.
            undated += selected
            continue
        counts[status] = counts.get(status, 0) + 1
        if not selected:
            continue
        matched.append(record)

    matched.sort(key=lambda r: str(timestamp_of(r) or ""), reverse=True)
    window = matched[offset : offset + limit] if limit is not None else matched[offset:]
    return Page(
        rows=[to_row(r) for r in window],
        total=len(matched),
        status_counts=counts,
        excluded_undated=undated,
    )


def _status_is_selected(status: str, allowed: set[str] | None) -> bool:
    """Whether the optional status facet admits one row."""
    return allowed is None or status in allowed


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


class _WindowVerdict(Enum):
    """Why a row is or is not in the window -- the distinction ``bool`` loses.

    Private because it is an answer :func:`paginate` needs and no caller does:
    a list surface reports the undated rows as a COUNT, not per row. Exposing
    it would invite each surface to re-decide what an unreadable timestamp
    means, which is the divergence this module exists to prevent.
    """

    INSIDE = "inside"
    OUTSIDE = "outside"
    UNDATED = "undated"
    """Bounded window, and the row carries no timestamp it could be judged by.

    Not a third kind of "outside". The row may well belong in the window; the
    query simply cannot be answered for it, and saying so is the difference
    between a filtered count and an honest one (#1215).
    """


def _window_verdict(
    value: object,
    after: datetime | None,
    before: datetime | None,
) -> _WindowVerdict:
    """Place ``value`` against the inclusive ``[after, before]``.

    An unbounded window admits everything, undated rows included: with no
    bound there is nothing a missing timestamp could fail.

    Bounds and rows are compared as UTC instants, so this never raises on a
    timezone-less value on either side and no caller has to normalise before
    calling; :func:`coerce_datetime` owns that reading and explains why the
    API's answer for a bound is a stricter one.
    """
    if after is None and before is None:
        return _WindowVerdict.INSIDE
    started = coerce_datetime(value)
    if started is None:
        return _WindowVerdict.UNDATED
    lower = coerce_datetime(after)
    upper = coerce_datetime(before)
    if lower is not None and started < lower:
        return _WindowVerdict.OUTSIDE
    if upper is not None and started > upper:
        return _WindowVerdict.OUTSIDE
    return _WindowVerdict.INSIDE


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

    That exclusion is right and stays. What was missing is that it was also
    SILENT: this returns the same ``False`` for "older than the bound" and for
    "no date at all", so a caller filtering on it cannot report the second
    (#1215). :func:`paginate` therefore does not use this - it asks
    :func:`_window_verdict` and counts the undated rows it dropped. Reach for
    this one only where a bare predicate is genuinely all that is wanted.
    """
    return _window_verdict(value, after, before) is _WindowVerdict.INSIDE


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
