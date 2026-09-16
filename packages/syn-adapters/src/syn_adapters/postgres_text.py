"""Make agent-produced text storable in Postgres (#1241, #781).

Agent output is untrusted: a tool can print any byte sequence it likes, and that
output is persisted verbatim into observability events, projections and session
metadata. Postgres cannot store every codepoint a Python ``str`` can hold, so an
agent that emits one fails the write - and the failure is not scoped to the one
field, it takes down the whole execution. Measured over 100 executions between
2026-09-08 and 2026-09-16: three died this way, burning $11.77, on

    unsupported Unicode escape sequence
    DETAIL: \\u0000 cannot be converted to text.

The invariant this module exists to hold: **untrusted text must never be able to
fail a write, or be stored as something other than what it said.** Every
Postgres write carrying agent-produced text passes its values through here
first, so no caller has to know which codepoints Postgres refuses, which ones
frame a COPY row, or what we do about either.

Those are two questions, not one, and they have different answers:

* :func:`pg_safe` / :func:`pg_json` remove codepoints Postgres cannot hold.
  Getting this wrong fails the write, loudly.
* :func:`pg_copy_row` escapes the characters COPY's text format reads as
  framing. Getting this wrong does NOT fail the write - it silently stores the
  data in the wrong columns.

Neither substitutes for the other: stripping a NUL does nothing about a tab,
and escaping a tab does nothing about a NUL.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from pydantic import JsonValue

__all__ = ["pg_copy_row", "pg_json", "pg_safe"]

# What Postgres refuses inside a text value - in a TEXT column, and as an escape
# in a JSONB document:
#
#   U+0000          a text value is NUL-terminated internally, so a NUL has no
#                   representation at all; jsonb rejects the escaped form for
#                   that same reason.
#   U+D800..U+DFFF  a lone surrogate is not valid UTF-8. Python holds them
#                   without complaint - json.loads accepts a bare surrogate
#                   escape out of an agent's own JSONL, and surrogateescape
#                   decoding manufactures them from undecodable bytes - so they
#                   arrive here from agent output the same way a NUL does.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def pg_safe[T](value: T) -> T:
    """Return ``value`` with every codepoint Postgres cannot store removed.

    Recurses into dicts, lists and tuples so a whole event payload can be handed
    over in one call; anything that is not a string is returned unchanged. Only
    real unstorable codepoints go: a literal ``"\\u0000"`` *text* sequence is six
    ordinary characters and survives untouched.
    """
    return cast("T", _sanitize(value))


def _sanitize(value: object) -> object:
    if isinstance(value, str):
        return _UNSTORABLE.sub("", value) if _UNSTORABLE.search(value) else value
    if isinstance(value, dict):
        items = cast("dict[object, object]", value).items()
        return {_sanitize(k): _sanitize(v) for k, v in items}
    if isinstance(value, list):
        return [_sanitize(v) for v in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(_sanitize(v) for v in cast("tuple[object, ...]", value))
    return value


def pg_json(data: Mapping[str, JsonValue]) -> str:
    """Serialize ``data`` to JSON text a ``jsonb`` column will accept.

    Sanitises first (see :func:`pg_safe`), and renders datetimes as ISO-8601,
    which is how every JSONB column in this system already stores a timestamp.
    """
    return json.dumps(pg_safe(dict(data)), default=_json_default)


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# COPY's text format frames a row with characters that also occur freely in
# agent output: TAB separates the fields, LF ends the row, and backslash escapes
# both. So an unescaped tab in a harness-supplied session id does not fail the
# write the way a NUL does - it shifts every field after it one column along and
# Postgres stores whatever lands where. At best the row count disagrees:
#
#     COPY field count: 7 (expected 6)
#
# at worst it does not, and the row is quietly wrong. A backslash is the same
# hazard one level down: JSON writes a tab as the two characters \t, and COPY
# reads those two characters as a tab, so an unescaped data payload arrives at
# the jsonb parser with a raw control character in a string literal.
#
# Translated in a single pass, so a backslash introduced by escaping is never
# re-escaped and the rules cannot be applied in the wrong order.
_COPY_ESCAPES = str.maketrans({"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"})

#: How COPY spells NULL. Callers pass ``None`` and never write this themselves.
_COPY_NULL = "\\N"


def pg_copy_row(fields: Iterable[str | None]) -> str:
    """Render ``fields`` as one COPY text-format row, terminator included.

    ``None`` is NULL. Every other value is escaped, so no character it contains
    can be read as a delimiter, a row terminator or an escape: the row Postgres
    parses always has exactly as many columns as ``fields`` had values, and each
    one holds the string that was passed in.

    Values must already be storable - see :func:`pg_safe`. This answers only
    where the fields begin and end, never what may be inside them.
    """
    return "\t".join(_copy_field(value) for value in fields) + "\n"


def _copy_field(value: str | None) -> str:
    return _COPY_NULL if value is None else value.translate(_COPY_ESCAPES)
