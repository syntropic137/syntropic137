"""One repository, by its `owner/repo` name, whatever shape it was stored in (#1837).

Repositories reach the platform as full URLs, `owner/repo` shorthands and git
remotes. Provisioning (`GH_REPO`, clone pins) and the `repos_display` label
both need the name, so the reduction lives here, below both of them.
"""

from __future__ import annotations

import re
from typing import Final

#: `owner` and `repo`: the two trailing path segments every accepted repo shape
#: ends with, whatever prefix it carries.
_OWNER_REPO_SEGMENTS: Final[int] = 2

#: An scp-style git remote, `user@host:path` (`git@github.com:owner/repo`). The
#: `user@` is required: without it a bare `a:b` is indistinguishable from a
#: Windows drive or plain text, and is not a remote anyone stores.
_SCP_REMOTE: Final = re.compile(r"[\w.-]+@[\w.-]+:(?P<path>.*)")

#: One `owner` or `repo` path segment. Anything else (a `:`, a `\`, a space)
#: means the entry is not a repository path, so it names no repo.
_SEGMENT: Final = re.compile(r"[\w.-]+")


def _path(text: str) -> str:
    """The path part of a stored repo, with its transport prefix removed.

    The prefix is recognised by its grammar (`scheme://host/`, `user@host:`),
    never by the host's name, so a repo or owner called `github.com` is a path
    segment like any other.
    """
    if "://" in text:
        _, _, rest = text.partition("://")
        _, _, path = rest.partition("/")
        return path
    scp = _SCP_REMOTE.fullmatch(text)
    if scp is not None:
        return scp["path"]
    return text


def owner_repo(repo: str) -> str | None:
    """`owner/repo` for one stored repository, or ``None`` when it names none.

    Accepts an `owner/repo` shorthand, a full URL on any host with or without
    `.git` or a trailing `/`, and `git@host:` / `ssh://` remotes.
    """
    text = repo.strip().rstrip("/").removesuffix(".git")
    parts = [part for part in _path(text).split("/") if part]
    if len(parts) < _OWNER_REPO_SEGMENTS:
        return None
    owner, name = parts[-2], parts[-1]
    if not (_SEGMENT.fullmatch(owner) and _SEGMENT.fullmatch(name)):
        return None
    return f"{owner}/{name}"
