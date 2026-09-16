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
fail a write.** Every Postgres write carrying agent-produced text passes its
values through here first, so no caller has to know which codepoints Postgres
refuses, or what we do about them.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import JsonValue

__all__ = ["pg_json", "pg_safe"]

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
