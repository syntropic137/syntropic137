"""Screened Text: the only form of reporter text an agent may read (ADR-076-feedback-ticketing).

Deterministic, so two submissions with the same words hash the same. The
secret-shape redaction is defence in depth and is NOT a PII control; the
publication policy is.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

MAX_SCREENED_CHARS = 4000
REDACTED = "[redacted]"

# C0 and C1 controls other than whitespace (whitespace is collapsed below),
# zero-width characters, and bidi embeddings, overrides and isolates.
_INVISIBLE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f"
    "​-‏⁠-⁤﻿"
    "‪-‮⁦-⁩]"
)
_WHITESPACE = re.compile(r"\s+")
_SECRET_SHAPES = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
    ),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}"),
)


class ScreenedText(BaseModel):
    """Normalised, redacted, capped reporter text. Build it with ``screen``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(max_length=MAX_SCREENED_CHARS)

    @classmethod
    def screen(cls, raw: str) -> ScreenedText:
        """NFC, drop invisible code points, collapse whitespace, redact, cap.

        Redaction runs before the cap so a cut can never leave half a secret.
        """
        text = _INVISIBLE.sub("", unicodedata.normalize("NFC", raw))
        text = _WHITESPACE.sub(" ", text).strip()
        for shape in _SECRET_SHAPES:
            text = shape.sub(REDACTED, text)
        return cls(text=text[:MAX_SCREENED_CHARS])

    @property
    def content_hash(self) -> str:
        """sha256 of the screened text: what events carry in place of the text."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()
