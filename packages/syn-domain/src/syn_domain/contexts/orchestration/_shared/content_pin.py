"""Shared invariant for content-addressed (``sha256-<hash>``) versions.

A ``sha256-<hash>`` version is a content commitment, not a label: it asserts
that the tree registered under it hashes to exactly that value. Skills and
claude plugins both pin content this way, so both enforce this, and they
enforce it identically because divergence between them IS the defect - the
two are meant to be the same guarantee.

Lives in ``_shared`` rather than in either slice so a third content-addressed
slice has one obvious thing to call. The enumerating test in
``tests/test_content_addressed_version_guards.py`` is what makes a new slice
actually call it, since a helper alone forces nothing.
"""

from __future__ import annotations

HASH_VERSION_PREFIX = "sha256-"


def declared_content_hash(version: str) -> str | None:
    """The hash a pinned version commits to, or None when it is not pinned.

    Deliberately case-sensitive: ``SHA256-`` is an ordinary version label, not
    a pin, and treating it as one would let a caller opt out of the check by
    changing case.
    """
    if not version.startswith(HASH_VERSION_PREFIX):
        return None
    return version[len(HASH_VERSION_PREFIX) :]


def content_pin_is_satisfied(version: str, actual_sha: str) -> bool:
    """Whether ``version`` either makes no commitment or names ``actual_sha``."""
    declared = declared_content_hash(version)
    return declared is None or declared == actual_sha
