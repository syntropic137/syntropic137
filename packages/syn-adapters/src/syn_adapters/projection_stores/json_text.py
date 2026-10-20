"""What an equality filter compares, for every projection store.

The Postgres store answers ``filters={"k": v}`` with ``data->>'k' = $n``: the
TEXT that ``->>`` extracts from the stored JSON, against the text of the filter
value. The in-memory store has to give the same answer, or a unit test can
certify a query production does not run. For a while it did not (#1675): it
compared Python values in ``query`` and ``str()`` in ``count``, so a stored
``1`` matched a filter of ``"1"`` in Postgres, in the in-memory ``count``, and
not in the in-memory ``query`` - three spellings of one predicate. A stored
``True`` matched ``"true"`` only in Postgres.

Both sides of the comparison live here so the stores share one definition.
"""

from __future__ import annotations

import json

from syn_adapters.postgres_text import pg_safe


def filter_text(value: object) -> str:
    """Render ``value`` the way the stored document renders the same thing.

    A filter is compared against ``data->>'key'``, and ``data`` was written
    through :func:`pg_json`, so this function's whole job is to land on the
    text the writer produced. Two things it did not previously do that for:

    JSONB ``->>`` extracts booleans as 'true'/'false' (lowercase JSON
    literals), but Python's ``str(False)`` produces 'False'.

    And the writer strips the codepoints Postgres cannot hold, so a filter
    value carrying one asks for text that was never stored under that name -
    the row is there, spelled without it, and the query returns nothing and
    says nothing (#1241). Every filter value gets the sanitiser, not just the
    ones on identity fields: the write applied it to the whole document, so
    any field a caller filters on is stored in its sanitised form.

    ``object`` rather than a union of the types a filter "should" carry. The
    union this replaced (`str | int | bool | float`) never described the
    callers: `_condition` takes ``object`` and passed it straight through, and
    the members of a collection filter are ``object`` too, which is the
    pyright error the collection support introduced. It did not even describe
    the tests, one of which pins ``None``. A name that has to be worked around
    at every call site is not documenting a restriction, only asserting one -
    and the body imposes none, because every object has a ``str()``.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return pg_safe(str(value))


def stored_text(value: object) -> str | None:
    """What ``data->>'key'`` extracts from a stored (already ``pg_safe``) value.

    ``None`` for a missing key or a JSON null: ``->>`` yields SQL NULL there,
    and NULL equals nothing, so no filter matches it. A string is its own
    text; everything else is its JSON literal. Numbers follow Python's JSON
    spelling, which agrees with JSONB's for the integers and plain decimals
    projections hold.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)
