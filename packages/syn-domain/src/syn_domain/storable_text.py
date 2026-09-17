"""The codepoints storage cannot hold, and what to do about them (#1241, #781).

Postgres cannot store every codepoint a Python ``str`` can hold. Agent output
is untrusted - a tool prints any byte sequence it likes, and a harness supplies
its own session id - so a write carrying one fails, and the failure takes down
the whole execution rather than the one field.

WHY THIS IS IN THE DOMAIN PACKAGE, given that the rule it encodes is Postgres's.
Because a write and the read that has to find it must agree about spelling, and
in this system those two sit on opposite sides of the package boundary: the
write is an adapter, while several read services - the cost, totals and heatmap
queries under ``contexts/*/slices/`` - hold an ``asyncpg`` pool and bind an id
into SQL themselves. Those cannot import ``syn_adapters`` (the dependency
direction runs the other way, and the layer-separation gate is at a clean
ratchet), so a copy here and a copy there is the only other option - and two
copies of a sanitiser that must agree is precisely the defect class this module
exists to close. One definition, in the lowest layer that needs it, is cheaper
to live with than the layering purity of two.

:mod:`syn_adapters.postgres_text` re-exports :func:`pg_safe` and adds what only
an adapter needs: JSON rendering, and COPY's row framing.
"""

from __future__ import annotations

import hashlib
import re
from typing import cast

__all__ = ["pg_safe"]

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

    This is what "the stored form of a value" means everywhere in this system.
    A write applies it; therefore a read that binds a value against stored text
    must apply it too, or it asks for a spelling nothing was ever written under
    and gets an empty result that reads as "nothing was recorded".
    """
    return cast("T", _sanitize(value))


#: Prefix on the derived form below. Chosen to be self-describing in a database
#: column at 2am, and long enough that no harness-generated id collides with it
#: by accident - the 64 hex digits that follow make that a non-question.
_UNSTORABLE_PREFIX = "unstorable-"

#: Marks a value that SURVIVED stripping but was changed by it. Without this,
#: stripping is not injective - `"session-a\x00b"` and `"session-ab"` both
#: become `"session-ab"` - and the two share every key derived from them.
_STRIPPED_INFIX = "-stripped-"

#: Half a sha256 is 64 bits of collision resistance on a value that is already
#: rare. The whole digest would make a session id unreadable in a column, which
#: is the property this form exists to keep.
_STRIPPED_DIGEST_LEN = 16


def _sanitize_str(value: str) -> str:
    """Strip the unstorable codepoints, unless that would erase the value.

    DELETION IS NOT INJECTIVE, and that is the whole problem this solves. An
    earlier version returned the stripped text whenever anything survived, so
    ``"session-a\\x00b"`` was stored as ``"session-ab"`` - the same key as a
    genuine ``"session-ab"``. Two different sessions then shared projection
    rows, conversation keys, import-ledger records and advisory locks, and the
    collision persisted across restarts. The all-unstorable case was handled
    and the partial case, which is the likelier one, was not.

    So the rule is now about whether the value CHANGED, not whether anything
    survived:

    * unchanged            -> returned as is
    * partially stripped   -> ``<stripped>-stripped-<16 hex>``
    * entirely stripped    -> ``unstorable-<64 hex>``

    Both derived forms are functions of the raw input alone, so a writer and a
    reader handed the same raw value agree without coordinating, and distinct
    inputs stay distinct. The readable part is kept in front precisely so the
    row is still recognisable in a column at 2am.

    ``surrogatepass`` because the lone surrogates in the class above are exactly
    what plain UTF-8 encoding refuses; it is the encoding that maps each of them
    to its own bytes, which is what "distinct values stay distinct" requires.

    Idempotent, like the rest of :func:`pg_safe`: the digest form contains no
    unstorable codepoint, so passing it through again returns it unchanged.
    """
    stripped = _UNSTORABLE.sub("", value)
    raw = value.encode("utf-8", "surrogatepass")
    digest = hashlib.sha256(raw).hexdigest()
    if not stripped:
        return _UNSTORABLE_PREFIX + digest
    return f"{stripped}{_STRIPPED_INFIX}{digest[:_STRIPPED_DIGEST_LEN]}"


def _sanitize(value: object) -> object:
    if isinstance(value, str):
        return _sanitize_str(value) if _UNSTORABLE.search(value) else value
    if isinstance(value, dict):
        items = cast("dict[object, object]", value).items()
        return {_sanitize(k): _sanitize(v) for k, v in items}
    if isinstance(value, list):
        return [_sanitize(v) for v in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(_sanitize(v) for v in cast("tuple[object, ...]", value))
    return value
