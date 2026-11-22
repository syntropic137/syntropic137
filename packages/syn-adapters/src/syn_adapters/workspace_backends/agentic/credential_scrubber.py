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
* base64 of a larger value the credential is part of (``user:<value>``),
  at each of the three byte alignments it can sit at, for a value of at
  least ``_EMBEDDED_MIN_BYTES``: the characters that carry only the value,
  and the edge characters that carry it alongside a neighbour, constrained
  to the ones its own bits allow - so every byte of the value is pinned and
  the edge bits it shares never leak;
* base64 wrapped at 64 or 76 columns (``openssl``, ``base64``): the whole
  wrapped text when it arrives in one line with escaped newlines, and each
  wrapped chunk wherever it stands as a base64 token of its own - a line, a
  JSON string, a word in a line. That holds for a larger value the
  credential is part of too: the wrap can fall anywhere in it, so a token is
  a fragment when it is a full-width line lying inside the value's encoding
  or touching it at an edge, or any shorter token that opens with the end of
  it (the last line). At most ``_FRAGMENT_MIN_CHARS - 1`` characters of the
  value can stand at either edge of a wrapped blob unmatched;
* URL-encoded (``%XX`` in either case, and ``+`` for space);
* JSON-escaped, so a value inside a JSON string matches as it is written.

EVERY NONEMPTY VALUE IS SCRUBBED, however short: the resolver accepts a short
value, so a short value can be a real credential.

JSON STAYS JSON. A line that matches and parses as JSON is scrubbed inside its
string values and re-serialized. A number that carries a value becomes the
marker as a JSON string, never bare text, so the line still parses. Any other line is scrubbed as text; the marker is
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


#: Shortest value matched inside a larger base64 value. Below it the run
#: that pins the value is a few characters, which ordinary words contain.
#: Shorter values are still matched raw and in their own encodings.
_EMBEDDED_MIN_BYTES = 6

_ALPHABETS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
)


def _sextet_class(alphabet: str, fixed: int, fixed_bits: int, high: bool) -> str:
    """A class of every character whose ``fixed_bits`` high or low bits are ``fixed``."""
    free = 6 - fixed_bits
    if high:
        chars = (alphabet[(fixed << free) | low] for low in range(1 << free))
    else:
        chars = (alphabet[(top << fixed_bits) | fixed] for top in range(1 << free))
    return "[" + "".join(re.escape(c) for c in chars) + "]"


def _aligned_encodings(value: bytes) -> list[tuple[str, str, str]]:
    """``value`` encoded at each byte offset inside a larger value.

    Each is ``(head, body, tail)``: the body is the characters that carry only
    the value's bits, the head and tail are patterns of the edge characters it
    shares with its neighbours.
    """
    if len(value) < _EMBEDDED_MIN_BYTES:
        return []
    aligned: list[tuple[str, str, str]] = []
    for alphabet in _ALPHABETS:
        for offset in range(3):
            bits = "".join(f"{b:08b}" for b in value)
            # Bits of the value that share a character with what precedes it.
            lead = (6 - 2 * offset) % 6
            head = ""
            if lead:
                head = _sextet_class(alphabet, int(bits[:lead], 2), lead, high=False)
            body_bits = bits[lead:]
            whole = len(body_bits) // 6
            body = "".join(alphabet[int(body_bits[i * 6 : i * 6 + 6], 2)] for i in range(whole))
            tail_bits = body_bits[whole * 6 :]
            tail = (
                _sextet_class(alphabet, int(tail_bits, 2), len(tail_bits), high=True)
                if tail_bits
                else ""
            )
            aligned.append((head, body, tail))
    return aligned


#: Shortest run of an encoded value that marks a wrapped token as a fragment
#: of it: six bytes, the same floor as ``_EMBEDDED_MIN_BYTES``.
_FRAGMENT_MIN_CHARS = 8

#: A base64 token, either alphabet, with its padding.
_BASE64_TOKEN = re.compile(rf"[A-Za-z0-9+/_-]{{{_FRAGMENT_MIN_CHARS},}}=*")


def _is_wrapped_fragment(token: str, body: str) -> bool:
    """Whether ``token`` is one line of a wrapped blob that carries ``body``.

    A full-width line lies inside the body, or ends with its start (the first
    line) or opens with its end (the last line). A shorter token can only be
    the last line, so only its opening counts: a near miss, which shares the
    body's start but not its end, is left alone. Only part of the body counts
    at an edge: the whole of it there is not a wrap, and the complete
    embedded pattern, edge characters included, decides it.
    """
    reach = min(len(token), len(body) - 1)
    opens_with_end = any(token.startswith(body[-n:]) for n in range(_FRAGMENT_MIN_CHARS, reach + 1))
    if len(token.rstrip("=")) not in _WRAP_WIDTHS:
        return opens_with_end
    return (
        opens_with_end
        or token in body
        or any(token.endswith(body[:n]) for n in range(_FRAGMENT_MIN_CHARS, reach + 1))
    )


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

    __slots__ = ("_bodies", "_chunks", "_pattern", "_reach", "_values")

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values = frozenset(v for v in values if v)
        forms: set[str] = set()
        embedded: set[str] = set()
        bodies: set[str] = set()
        self._chunks: frozenset[str] = frozenset()
        # The longest text one match can span: a form, a wrapped chunk, or an
        # aligned encoding with the two edge characters it shares.
        self._reach = 0
        for value in self._values:
            whole, chunks = _encodings(value)
            forms |= whole
            aligned = _aligned_encodings(value.encode("utf-8"))
            self._reach = max(
                self._reach,
                *(len(f) for f in (*whole, *chunks)),
                *(len(body) + 2 for _, body, _ in aligned),
            )
            embedded |= {head + re.escape(body) + tail for head, body, tail in aligned}
            bodies |= {body for _, body, _ in aligned if len(body) >= _FRAGMENT_MIN_CHARS}
            self._chunks |= chunks
        self._bodies = tuple(bodies)
        # Longest first, so a value is never half-replaced by a shorter form
        # that happens to be its prefix. Every form is escaped: a secret is
        # matched as text, never interpreted as a pattern. Embedded base64
        # comes last: a complete encoding is replaced whole, padding included.
        patterns = [_pattern_of(f) for f in sorted(forms, key=len, reverse=True)]
        patterns += sorted(embedded, key=len, reverse=True)
        self._pattern = re.compile("|".join(patterns)) if patterns else None

    @property
    def reach(self) -> int:
        """The most characters one match can span (0 when there is nothing to withhold).

        What a reader scrubbing text in pieces rather than lines must hold back
        at each cut, so a value split across two pieces is still whole when it
        is scrubbed (ADR-078 D3).
        """
        return self._reach

    def covers(self, values: Iterable[str]) -> bool:
        """Whether this scrubber already matches exactly ``values``."""
        return self._values == frozenset(v for v in values if v)

    def scrub(self, line: str) -> str:
        """``line`` with every credential value in it replaced."""
        if self._pattern is None:
            return line
        if line.strip() in self._chunks:
            return REDACTED_MARKER
        # Escaped newlines unescaped, so a wrapped blob inside one JSON string
        # splits into its lines here as it does once the string is decoded.
        if (
            self._pattern.search(line) is None
            and not any(
                self._is_fragment(m.group())
                for m in _BASE64_TOKEN.finditer(line.replace("\\n", "\n"))
            )
            and not any(f'"{chunk}"' in line for chunk in self._chunks)
        ):
            return line
        try:
            document = json.loads(line)
        except ValueError:
            return self._scrub_text(line)
        if not isinstance(document, dict | list):
            return self._scrub_text(line)
        return json.dumps(self._scrub_json(document), ensure_ascii=False, separators=(",", ":"))

    def _is_fragment(self, token: str) -> bool:
        """Whether ``token`` is one wrapped line of a value's base64."""
        return token in self._chunks or any(
            _is_wrapped_fragment(token, body) for body in self._bodies
        )

    def _scrub_text(self, text: str) -> str:
        """``text`` with every value and every wrapped fragment of one replaced."""
        assert self._pattern is not None
        return _BASE64_TOKEN.sub(
            lambda m: REDACTED_MARKER if self._is_fragment(m.group()) else m.group(),
            self._pattern.sub(REDACTED_MARKER, text),
        )

    def _scrub_json(self, node: object) -> object:
        """``node`` with every string in it, keys included, scrubbed as text.

        A number is scrubbed as the text JSON writes it, and becomes the
        marker as a string when that text carries a value.
        """
        assert self._pattern is not None
        if isinstance(node, str):
            # A chunk too short to be a token on its own still is one when it
            # is the whole string, as it is the whole line above.
            return REDACTED_MARKER if node.strip() in self._chunks else self._scrub_text(node)
        if isinstance(node, list):
            return [self._scrub_json(item) for item in node]
        if isinstance(node, dict):
            return {self._scrub_text(key): self._scrub_json(item) for key, item in node.items()}
        if isinstance(node, int | float) and not isinstance(node, bool):
            return REDACTED_MARKER if self._pattern.search(json.dumps(node)) else node
        return node

    def __repr__(self) -> str:
        return f"CredentialScrubber(<{len(self._values)} values>)"


def scrub_bytes(scrubber: CredentialScrubber, content: bytes) -> bytes:
    """``content`` scrubbed line by line, every byte outside a match kept.

    Bytes that are not UTF-8 survive the round trip as surrogate escapes, so
    a binary file nothing matches comes back unchanged.
    """
    text = content.decode("utf-8", errors="surrogateescape")
    scrubbed = "\n".join(scrubber.scrub(line) for line in text.split("\n"))
    return scrubbed.encode("utf-8", errors="surrogateescape")
