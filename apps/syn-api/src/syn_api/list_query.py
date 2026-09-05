"""The query contract the list endpoints share.

``/executions`` and ``/sessions`` present the same thing -- a filtered,
ordered, paged collection with status facets -- so they answer to the same
parameters. Where each endpoint spelled its own, they drifted: one capped a
page at 100 and the other at 200, one took ``statuses`` and the other did not,
and neither could be paged past its first page (#1159, #1160).

These helpers are the decisions a caller should not have to re-derive: which
statuses a request selected, how big a page is, and what a time bound has to
say before the server will act on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator

DEFAULT_PAGE_SIZE = 50
"""Page size when the request asks for none."""

MAX_PAGE_SIZE = 200
"""Safety cap on one response, not a UI page size.

The 100/200 asymmetry between the two endpoints was an accident of two
unrelated refactors and no ADR ever named a value; 200 is the larger of the
two, so raising ``/executions`` to match widens nothing that was not already
reachable on ``/sessions``.
"""


def parse_statuses(statuses: str | None, status: str | None) -> list[str] | None:
    """The statuses a request selected, or None for "any".

    ``statuses`` is a comma-separated multi-select and takes precedence over the
    legacy single-valued ``status``. Blank entries are dropped, so ``"a,,b"``
    and a trailing comma mean what they look like.
    """
    if statuses:
        parsed = [s.strip() for s in statuses.split(",") if s.strip()]
        if parsed:
            return parsed
    return [status] if status else None


def resolve_page_size(page_size: int | None, limit: int | None = None) -> int:
    """How many rows this request wants, honouring the deprecated ``limit`` alias.

    ``page_size`` wins when both are given. That is only expressible because
    both default to None rather than to 50 -- with a concrete default the
    endpoint cannot tell "omitted" from "explicitly 50", and the precedence
    rule has nothing to read.
    """
    if page_size is not None:
        return page_size
    if limit is not None:
        return limit
    return DEFAULT_PAGE_SIZE


def _require_timezone(value: datetime) -> datetime:
    """Refuse a bound that does not say which instant it means (#1183).

    FastAPI parses ``?started_after=2026-09-01T00:00:00`` into a NAIVE
    datetime and accepts it, and a bare ``2026-09-01`` the same way. Rows carry
    aware UTC timestamps, so the comparison raised ``TypeError`` and the
    endpoint answered 500.

    Not crashing is the floor, not the contract. The question is what a bound
    with no offset MEANS, and the honest answer is that the server does not
    know: someone in PST typing local midnight and someone scripting UTC write
    it identically, and reading it as UTC shifts the first one's window by
    eight hours and returns a confidently wrong page with nothing to indicate
    it. Refusing is the correct answer to an ambiguous question -- 422 names
    the problem and the caller adds four characters, where a guess produces a
    number they have no way to distrust.

    This is only defensible because there is a caller to tell. Timestamps
    already IN the store get the opposite treatment for the opposite reason:
    see ``syn_domain.pagination.coerce_datetime``, where nobody is around to be
    asked and UTC is the only reading the data supports.
    """
    if value.tzinfo is None:
        msg = (
            "requires a timezone: send 2026-09-01T00:00:00Z or "
            "2026-09-01T00:00:00+00:00 (a value with no offset is ambiguous, "
            "and a bare date has none)"
        )
        raise ValueError(msg)
    return value


WindowBound = Annotated[datetime, AfterValidator(_require_timezone)]
"""A ``started_after`` / ``started_before`` bound, offset required.

One name so the two endpoints cannot answer differently: they share the
comparator these bounds are fed to, so a value the API accepts on one and
refuses on the other would be a difference with nothing behind it.
"""
