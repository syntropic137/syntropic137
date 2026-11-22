"""RepoNamePort - what the github context asks for a trigger's GitHub name.

A trigger names its repository as GitHub does (``owner/name``) or by a syn137
repo id (``repo-…``), and only the first can be polled. The organization
context owns what an id resolves to, so the composition root binds this port to
its Repo record and the github context never imports it (#1870).
"""

from __future__ import annotations

from typing import Protocol


class RepoNamePort(Protocol):
    """Resolves a repository as a trigger names it to GitHub's ``owner/name``."""

    async def full_name(self, repository: str) -> str | None:
        """``owner/name`` for ``repository``, or None when nothing says what it is.

        ``owner/name`` comes back as given. A ``repo-…`` id comes back as its
        Repo record's full name, and as None when there is no such record.
        """
        ...
