"""Repository identity value object for cross-context boundaries.

Provides a typed, normalized representation of repository identity that
replaces implicit dict-key conventions (``inputs["repository"]`` vs
``inputs["repos"]``) at bounded context boundaries.

See: ADR-063 (Cross-Context Anti-Corruption Layer)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches owner/repo slug (no protocol prefix)
_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

# Matches https://github.com/owner/repo (with optional trailing slash or .git)
_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9._-]+)/(?P<name>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class RepositoryRef:
    """Immutable repository identity.

    Normalizes the two representations used across bounded contexts:
    - GitHub context: ``owner/repo`` slug (from webhook payloads)
    - Orchestration context: ``https://github.com/owner/repo`` URL (for git clone)

    Construct via ``from_slug()`` or ``from_url()``, then access either
    form via ``.slug`` or ``.https_url``.
    """

    owner: str
    name: str

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("RepositoryRef.owner cannot be empty")
        if not self.name:
            raise ValueError("RepositoryRef.name cannot be empty")

    @classmethod
    def from_slug(cls, slug: str) -> RepositoryRef:
        """Construct from ``owner/repo`` slug format.

        Raises:
            ValueError: If slug is not in ``owner/repo`` format.
        """
        if not _SLUG_RE.match(slug):
            raise ValueError(f"Invalid repository slug: '{slug}'. Expected 'owner/repo' format.")
        owner, name = slug.split("/", 1)
        return cls(owner=owner, name=name)

    @classmethod
    def from_url(cls, url: str) -> RepositoryRef:
        """Construct from a GitHub HTTP(S) URL.

        Accepts ``https://github.com/owner/repo`` or ``http://...``,
        with optional trailing slash or ``.git`` suffix.
        The canonical output (via ``.https_url``) always uses HTTPS.

        Raises:
            ValueError: If URL doesn't match expected GitHub format.
        """
        match = _URL_RE.match(url)
        if not match:
            raise ValueError(
                f"Invalid repository URL: '{url}'. Expected 'https://github.com/owner/repo' format."
            )
        return cls(owner=match.group("owner"), name=match.group("name"))

    @classmethod
    def parse(cls, value: str) -> RepositoryRef:
        """Parse from either slug or URL format.

        Tries URL first (more specific), falls back to slug.

        Raises:
            ValueError: If value doesn't match either format.
        """
        if value.startswith(("https://", "http://")):
            return cls.from_url(value)
        return cls.from_slug(value)

    @property
    def slug(self) -> str:
        """Return ``owner/repo`` format (GitHub context canonical form)."""
        return f"{self.owner}/{self.name}"

    @property
    def https_url(self) -> str:
        """Return ``https://github.com/owner/repo`` (orchestration canonical form)."""
        return f"https://github.com/{self.owner}/{self.name}"

    def __str__(self) -> str:
        return self.slug

    def __repr__(self) -> str:
        return f"RepositoryRef('{self.slug}')"
