"""One repository, by its `owner/repo` name, whatever shape it was stored in (#1837).

Repositories reach the platform as full URLs, `owner/repo` shorthands and git
remotes. Provisioning (`GH_REPO`, clone pins) and the `repos_display` label
both need the name, so the reduction lives here, below both of them.
"""

from __future__ import annotations

from typing import Final

#: `owner` and `repo`: the two trailing path segments every accepted repo shape
#: ends with, whatever prefix it carries.
_OWNER_REPO_SEGMENTS: Final[int] = 2


def owner_repo(repo: str) -> str | None:
    """`owner/repo` for one stored repository, or ``None`` when it names none.

    Accepts an `owner/repo` shorthand, a full URL on any host with or without
    `.git` or a trailing `/`, and `git@` / `ssh://` remotes.
    """
    text = repo.strip().rstrip("/").removesuffix(".git")
    if "github.com" in text:
        _, _, text = text.partition("github.com")
    elif "://" in text:
        _, _, text = text.partition("://")
        _, _, text = text.partition("/")
    parts = [part for part in text.replace(":", "/").split("/") if part]
    if len(parts) < _OWNER_REPO_SEGMENTS:
        return None
    return f"{parts[-2]}/{parts[-1]}"
