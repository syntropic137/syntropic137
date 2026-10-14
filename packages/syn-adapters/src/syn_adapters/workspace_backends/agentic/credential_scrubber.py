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
* base64, standard and URL-safe, the complete encoding with or without its
  padding, so a value differing only in its last byte is left alone;
* base64 wrapped at 64 or 76 columns (``openssl``, ``base64``): the whole
  wrapped text when it arrives in one line with escaped newlines, and each
  wrapped chunk when it arrives as a line of its own;
* URL-encoded (``%XX`` in either case, and ``+`` for space);
* JSON-escaped, so a value inside a JSON string matches as it is written.

EVERY NONEMPTY VALUE IS SCRUBBED, however short: the resolver accepts a short
value, so a short value can be a real credential.

JSON STAYS JSON. A line that matches and parses as JSON is scrubbed inside its
string values and re-serialized, so a number that happens to equal a value is
never replaced by bare text. Any other line is scrubbed as text; the marker is
plain ASCII with no quote or backslash, so that is safe inside a string too.
A line nothing matches is returned unchanged, byte for byte, after one search.

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

#: Column widths base64 tools wrap at: ``openssl base64`` and ``base64``.
_WRAP_WIDTHS = (64, 76)


def _base64_forms(value: bytes) -> tuple[set[str], set[str]]:
    """Complete base64 encodings of ``value``, and the chunks they wrap into.

    Only complete encodings: the characters around a value's edges depend on
    its last byte, so matching less than all of them would also rewrite a
    near miss that differs only there.
    """
    whole: set[str] = set()
    chunks: set[str] = set()
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        encoded = encode(value).decode("ascii")
        whole.update((encoded, encoded.rstrip("=")))
        for width in _WRAP_WIDTHS:
            if len(encoded) <= width:
                continue
            wrapped = [encoded[i : i + width] for i in range(0, len(encoded), width)]
            # Escaped as JSON writes it, and as the decoded string reads.
            whole.update(("\\n".join(wrapped), "\n".join(wrapped)))
            chunks.update(wrapped)
    return whole, chunks


def _pattern_of(form: str) -> str:
    """``form`` as a pattern: escaped, with percent escapes matched in either case."""
    parts = re.split(r"(%[0-9A-F]{2})", form)
    return "".join(f"(?i:{p})" if i % 2 else re.escape(p) for i, p in enumerate(parts))


def _encodings(value: str) -> tuple[set[str], set[str]]:
    """Every form of ``value`` matched inside a line, and every wrapped chunk."""
    forms = {value, quote(value, safe=""), quote_plus(value, safe="")}
    escaped = json.dumps(value)[1:-1]
    forms |= {escaped, escaped.replace("/", "\\/")}
    whole, chunks = _base64_forms(value.encode("utf-8"))
    return forms | whole, chunks


class CredentialScrubber:
    """Replaces every known credential value in a line with ``REDACTED_MARKER``."""

    __slots__ = ("_chunks", "_pattern", "_values")

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values = frozenset(v for v in values if v)
        forms: set[str] = set()
        self._chunks: frozenset[str] = frozenset()
        for value in self._values:
            whole, chunks = _encodings(value)
            forms |= whole
            self._chunks |= chunks
        # Longest first, so a value is never half-replaced by a shorter form
        # that happens to be its prefix. Every form is escaped: a secret is
        # matched as text, never interpreted as a pattern.
        self._pattern = (
            re.compile("|".join(_pattern_of(f) for f in sorted(forms, key=len, reverse=True)))
            if forms
            else None
        )

    def covers(self, values: Iterable[str]) -> bool:
        """Whether this scrubber already matches exactly ``values``."""
        return self._values == frozenset(v for v in values if v)

    def scrub(self, line: str) -> str:
        """``line`` with every credential value in it replaced."""
        if self._pattern is None:
            return line
        if line.strip() in self._chunks:
            return REDACTED_MARKER
        if self._pattern.search(line) is None:
            return line
        try:
            document = json.loads(line)
        except ValueError:
            return self._pattern.sub(REDACTED_MARKER, line)
        if not isinstance(document, dict | list):
            return self._pattern.sub(REDACTED_MARKER, line)
        return json.dumps(self._scrub_json(document), ensure_ascii=False, separators=(",", ":"))

    def _scrub_json(self, node: object) -> object:
        """``node`` with every string in it, keys included, scrubbed as text."""
        assert self._pattern is not None
        if isinstance(node, str):
            return self._pattern.sub(REDACTED_MARKER, node)
        if isinstance(node, list):
            return [self._scrub_json(item) for item in node]
        if isinstance(node, dict):
            return {
                self._pattern.sub(REDACTED_MARKER, key): self._scrub_json(item)
                for key, item in node.items()
            }
        return node

    def __repr__(self) -> str:
        return f"CredentialScrubber(<{len(self._values)} values>)"
