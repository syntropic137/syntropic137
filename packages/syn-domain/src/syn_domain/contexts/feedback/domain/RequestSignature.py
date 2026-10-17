"""Signed-lane request verification: canonical string, signature, timestamp window (ADR-076-feedback-ticketing).

Pure: no clock, no I/O, no settings. The caller passes ``now`` and the rotation
overlap, so the same inputs always give the same verdict, and Intake (plan
PR 3) decides where those values come from.

The algorithm is owner decision D2 and is not made yet. It sits behind
``SignatureAlgorithm``; ``Ed25519Signatures`` is the recommended one. Moving to
HMAC is one new class with the same two methods - nothing else here changes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import SourceKey  # noqa: TC001

#: Plan s2.3: a signature older or newer than this is refused. Inclusive.
SIGNATURE_WINDOW = timedelta(seconds=300)


class SignedRequest(BaseModel):
    """What arrives on the signed lane: the request and its ``X-Syn-*`` headers.

    ``timestamp`` is Unix seconds (``X-Syn-Timestamp``); ``body`` is the raw
    bytes exactly as received, never a re-serialisation of the parsed JSON.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str = Field(min_length=1, max_length=16)
    path: str = Field(min_length=1, max_length=512)
    timestamp: int
    nonce: str = Field(min_length=1, max_length=128)
    body: bytes
    key_id: str = Field(min_length=1, max_length=64)
    signature: str = Field(min_length=1, max_length=512)

    def canonical(self) -> bytes:
        return canonical_string(
            method=self.method,
            path=self.path,
            timestamp=self.timestamp,
            nonce=self.nonce,
            body=self.body,
        )


def canonical_string(*, method: str, path: str, timestamp: int, nonce: str, body: bytes) -> bytes:
    """``method \\n path \\n ts \\n nonce \\n sha256(body)``: the bytes a source signs.

    Every field that makes a request distinct is in here. Leave one out and a
    captured signature can be replayed with that field changed.
    """
    digest = hashlib.sha256(body).hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode()


class SignatureAlgorithm(Protocol):
    """D2's seam. ``verification_key`` is what a SourceEnrolled event may hold."""

    def sign(self, signing_key: bytes, message: bytes) -> str:
        """Base64 signature over ``message``. Runs on the Relay, never at Intake."""
        ...

    def verify(self, verification_key: str, message: bytes, signature: str) -> bool:
        """True only for a well-formed, valid signature. Malformed input is False, not an error."""
        ...


class Ed25519Signatures:
    """Ed25519 (RFC 8032). A leaked central database holds only public keys, so cannot forge."""

    def sign(self, signing_key: bytes, message: bytes) -> str:
        private = Ed25519PrivateKey.from_private_bytes(signing_key)
        return base64.b64encode(private.sign(message)).decode()

    def verify(self, verification_key: str, message: bytes, signature: str) -> bool:
        try:
            public = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(verification_key, validate=True)
            )
            public.verify(base64.b64decode(signature, validate=True), message)
        except (InvalidSignature, ValueError, binascii.Error):
            # Every way a forged or garbled request can fail is one answer: not verified.
            return False
        return True


class SourceCredentials(BaseModel):
    """What the verifier needs to know about one Source, as the feedback_sources projection holds it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    revoked: bool
    keys: tuple[SourceKey, ...]


class Verification(StrEnum):
    """The verdict on a signed request. Only ``VERIFIED`` admits it.

    The other values are distinct so Intake can count them separately; the
    HTTP answer is the same 401 for all of them.
    """

    VERIFIED = "verified"
    REVOKED = "revoked"
    STALE_TIMESTAMP = "stale_timestamp"
    UNKNOWN_KEY = "unknown_key"
    KEY_RETIRED = "key_retired"
    BAD_SIGNATURE = "bad_signature"


class SignatureVerifier:
    """Decides whether a signed request comes from the Source it names, now.

    ``rotation_overlap`` is how long a key replaced by a rotation keeps
    verifying (plan s2.1, a setting from PR 3 on). Revocation outranks it.
    """

    def __init__(
        self,
        algorithm: SignatureAlgorithm,
        *,
        rotation_overlap: timedelta,
        window: timedelta = SIGNATURE_WINDOW,
    ) -> None:
        self._algorithm = algorithm
        self._rotation_overlap = rotation_overlap
        self._window = window

    def verify(
        self, request: SignedRequest, credentials: SourceCredentials, *, now: datetime
    ) -> Verification:
        if credentials.revoked:
            return Verification.REVOKED
        signed_at = datetime.fromtimestamp(request.timestamp, tz=UTC)
        if abs(now - signed_at) > self._window:
            return Verification.STALE_TIMESTAMP
        key = next((k for k in credentials.keys if k.key_id == request.key_id), None)
        if key is None:
            return Verification.UNKNOWN_KEY
        if key.retired_at is not None and now >= key.retired_at + self._rotation_overlap:
            return Verification.KEY_RETIRED
        if not self._algorithm.verify(key.verification_key, request.canonical(), request.signature):
            return Verification.BAD_SIGNATURE
        return Verification.VERIFIED
