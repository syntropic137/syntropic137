"""Deterministic claim ID for the stream-per-unique-value pattern.

The claim ID is a truncated SHA-256 hash of the uniqueness key
``(organization_id, provider, full_name)``.  It always maps the same
logical tuple to the same event stream, so the event store can enforce
uniqueness atomically via ``ExpectedVersion.NO_STREAM``.
"""

from __future__ import annotations

import hashlib


def compute_repo_claim_id(
    organization_id: str,
    provider: str,
    full_name: str,
) -> str:
    """Return a deterministic claim ID for the given repo identity.

    Format: ``rc-{16-char-hex}`` (64 bits of SHA-256).
    """
    key = f"{organization_id}:{provider}:{full_name}"
    return f"rc-{hashlib.sha256(key.encode()).hexdigest()[:16]}"
