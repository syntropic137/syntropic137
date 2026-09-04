"""The query contract the list endpoints share.

``/executions`` and ``/sessions`` present the same thing -- a filtered,
ordered, paged collection with status facets -- so they answer to the same
parameters. Where each endpoint spelled its own, they drifted: one capped a
page at 100 and the other at 200, one took ``statuses`` and the other did not,
and neither could be paged past its first page (#1159, #1160).

These helpers are the two decisions a caller should not have to re-derive:
which statuses a request selected, and how big a page is.
"""

from __future__ import annotations

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
