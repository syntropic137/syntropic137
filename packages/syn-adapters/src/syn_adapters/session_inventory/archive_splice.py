"""Envelope-splice references: an older revision stored as a slice of the newest (#2107).

A capture envelope is JSON whose last key is ``raw``, the native transcript as
one string. Transcripts are append-only, so an older revision's ``raw`` is a
prefix of the newest one's, and JSON escaping is per character, so the prefix
holds on the encoded bytes too. Only the envelope head (timestamps, counts) and
the closing tail differ. So, on UNCOMPRESSED envelope bytes::

    older == reference.head + base[offset : offset + length] + reference.tail

Everything here is pure. Nothing is trusted: a plan is only a candidate, and
the archive verifies the reconstruction by size and sha256 before it commits a
reference, and again on every read. A revision that does not fit stays a full
object.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_DIGEST = r"^[0-9a-f]{64}$"
_RAW_KEY = b'"raw":"'
# After the raw string only the object close may follow.
_TAIL = re.compile(rb'"\s*}\s*')
IDENTITY_KEY = b',"raw":'


class SpliceReference(BaseModel):
    """How to rebuild ``sha256`` from the full object ``base_sha256``."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", ser_json_bytes="base64", val_json_bytes="base64"
    )

    sha256: str = Field(pattern=_DIGEST)
    size: int = Field(ge=0)
    base_sha256: str = Field(pattern=_DIGEST)
    base_size: int = Field(ge=0)
    offset: int = Field(ge=0)
    length: int = Field(ge=0)
    head: bytes
    tail: bytes


def _raw_span(envelope: bytes) -> tuple[int, int] | None:
    """Start and end of the ``raw`` string's encoded contents, if it is the last key.

    The raw string escapes every quote, so the last unescaped ``"raw":"`` is the
    top-level key. A wrong guess only costs a splice: the caller verifies.
    """
    key = envelope.rfind(_RAW_KEY)
    end = envelope.rfind(b'"')
    start = key + len(_RAW_KEY)
    if key < 0 or end < start or not _TAIL.fullmatch(envelope, end):
        return None
    return start, end


def _span(older: bytes, base: bytes) -> tuple[int, int, int] | None:
    """(start in older, end in older, offset in base) of the shared slice."""
    if base.startswith(older):
        return 0, len(older), 0
    spans = _raw_span(older), _raw_span(base)
    if spans[0] is None or spans[1] is None:
        return None
    (start, end), (offset, _) = spans[0], spans[1]
    if base[offset : offset + end - start] != older[start:end]:
        return None
    return start, end, offset


def plan_splice(older: bytes, base: bytes) -> SpliceReference | None:
    """A candidate reference for ``older`` against ``base``; ``None`` if it is not a prefix."""
    span = _span(older, base)
    if span is None:
        return None
    start, end, offset = span
    return SpliceReference(
        sha256=hashlib.sha256(older).hexdigest(),
        size=len(older),
        base_sha256=hashlib.sha256(base).hexdigest(),
        base_size=len(base),
        offset=offset,
        length=end - start,
        head=older[:start],
        tail=older[end:],
    )


def reconstruct(reference: SpliceReference, base: bytes) -> bytes | None:
    """The bytes ``reference`` names, or ``None`` unless they verify exactly."""
    return assemble(
        reference, len(base), base[reference.offset : reference.offset + reference.length]
    )


def assemble(reference: SpliceReference, base_size: int, middle: bytes) -> bytes | None:
    """``reference`` around ``middle``, the slice read from a verified base of ``base_size`` bytes.

    ``None`` unless the result verifies exactly; a short slice is a base too short.
    """
    if base_size != reference.base_size or len(middle) != reference.length:
        return None
    body = reference.head + middle + reference.tail
    if len(body) != reference.size or hashlib.sha256(body).hexdigest() != reference.sha256:
        return None
    return body


class _Identity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    agent: str
    session_id: str


def envelope_identity(prefix: bytes) -> tuple[str, str] | None:
    """(agent, session_id) from the start of an envelope; revisions share it.

    The head is everything before the top-level ``raw`` key. A nested ``raw``
    key earlier cuts the JSON mid-object and fails to parse, so each candidate
    cut is tried in order.
    """
    cut = prefix.find(IDENTITY_KEY)
    while cut >= 0:
        try:
            head = _Identity.model_validate_json(prefix[:cut] + b"}")
        except ValidationError:
            cut = prefix.find(IDENTITY_KEY, cut + 1)
            continue
        return head.agent, head.session_id
    return None
