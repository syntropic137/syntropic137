"""Credential values a workload prints never leave the stream boundary (#1927).

A workspace holds credentials the agent can read: its environment carries the
platform grant and the model key, the session-store token is bound into it,
and the setup phase writes GitHub installation tokens to files in it. Anything
the agent prints reaches the yielded lines, and from there the logs, Lane 2
tool events and captured artifacts. So every value is replaced by
``REDACTED_MARKER`` before a line is yielded.

VALUE-BASED, NOT FORMAT-BASED. The scrubber knows the secrets, not how any
harness frames its output, so it works the same on Claude and Codex JSONL and
on a bare ``echo``. It also matches the encodings an agent is likely to print
a value in:

* raw;
* base64, standard and URL-safe, at all three byte alignments, so a value
  embedded in a longer encoded blob is still found;
* URL-encoded (``%XX`` and ``+`` for space);
* JSON-escaped, so a value inside a JSON string matches as it is written.

The marker is plain ASCII with no quote or backslash, so replacing a match
inside a JSON string value leaves the document valid.

A value shorter than ``MIN_SECRET_LENGTH`` is ignored. Every real credential is
much longer, and scrubbing a short value would rewrite ordinary output.

This module never logs a value and its ``repr`` names none.
"""

from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING
from urllib.parse import quote, quote_plus

if TYPE_CHECKING:
    from collections.abc import Iterable

#: What a credential value is replaced with. Never matched by any encoding of
#: a real secret, and safe inside a JSON string.
REDACTED_MARKER = "[REDACTED:credential]"

#: Shortest value, and shortest encoded form, that is scrubbed.
MIN_SECRET_LENGTH = 8


def _base64_cores(value: bytes) -> set[str]:
    """The base64 characters fixed by ``value`` alone, at each byte alignment.

    Encoding ``value`` after k bytes of anything changes the first characters
    (they mix with the k bytes) and the last (they mix with whatever follows).
    The characters between depend on ``value`` only, so they are what appears
    whenever ``value`` is part of a longer encoded stream.
    """
    cores: set[str] = set()
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + value).decode("ascii")
        total = offset + len(value)
        head = (0, 2, 3)[offset]
        tail = (total // 3) * 4 + (0, 1, 2)[total % 3]
        core = encoded[head:tail]
        cores.add(core)
        cores.add(core.translate(str.maketrans("+/", "-_")))
    return cores


def _encodings(value: str) -> set[str]:
    """Every form of ``value`` this scrubber looks for."""
    forms = {value, quote(value, safe=""), quote_plus(value, safe="")}
    escaped = json.dumps(value)[1:-1]
    forms |= {escaped, escaped.replace("/", "\\/")}
    forms |= _base64_cores(value.encode("utf-8"))
    return {form for form in forms if len(form) >= MIN_SECRET_LENGTH}


class CredentialScrubber:
    """Replaces every known credential value in a line with ``REDACTED_MARKER``."""

    __slots__ = ("_pattern", "_values")

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values = frozenset(v for v in values if len(v) >= MIN_SECRET_LENGTH)
        forms = set[str]().union(*(_encodings(v) for v in self._values))
        # Longest first, so a value is never half-replaced by a shorter form
        # that happens to be its prefix. Every form is escaped: a secret is
        # matched as text, never interpreted as a pattern.
        self._pattern = (
            re.compile("|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)))
            if forms
            else None
        )

    def covers(self, values: Iterable[str]) -> bool:
        """Whether this scrubber already matches exactly ``values``."""
        return self._values == frozenset(v for v in values if len(v) >= MIN_SECRET_LENGTH)

    def scrub(self, line: str) -> str:
        """``line`` with every credential value in it replaced."""
        if self._pattern is None:
            return line
        return self._pattern.sub(REDACTED_MARKER, line)

    def __repr__(self) -> str:
        return f"CredentialScrubber(<{len(self._values)} values>)"
