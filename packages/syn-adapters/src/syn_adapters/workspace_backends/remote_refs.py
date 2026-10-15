"""`RemoteRefs` over ``git ls-remote``: what a remote holds, asked of the remote (#1983).

A workspace's ``refs/remotes/*`` are files the agent could write, and so is
the ``remote.origin.url`` in its config. Neither proves a commit is anywhere
but on this disk. So the reclaimer asks the remote itself, at the URL the
Execution's domain record names, and only what it advertises counts.

``git ls-remote`` runs outside every workspace (``-C /``) with no system,
global or repository config, so nothing an agent wrote takes effect. A GitHub
URL is read with an App installation token scoped to that one repository,
read-only, passed through ``GIT_CONFIG_*`` environment entries rather than
argv, where any local user could read it.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

#: The design's bound for one remote read (#1983, 1.2).
LS_REMOTE_TIMEOUT_SECONDS = 30.0

_OID = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


class RemoteRefsError(RuntimeError):
    """The remote could not say what it holds."""


class GitLsRemote:
    """Reads every object id a remote advertises. Raises `RemoteRefsError` otherwise.

    ``credential`` returns the ``Authorization`` header value for a URL, or
    None to read it anonymously.
    """

    def __init__(
        self,
        credential: Callable[[str], Awaitable[str | None]] | None = None,
        *,
        timeout: float = LS_REMOTE_TIMEOUT_SECONDS,
    ) -> None:
        self._credential = credential
        self._timeout = timeout

    async def advertised(self, url: str) -> frozenset[str]:
        if not url or url.startswith("-"):
            raise RemoteRefsError(f"refusing remote {url!r}")
        env = _ls_remote_env()
        if self._credential is not None:
            header = await self._credential(url)
            if header is not None:
                env.update(
                    {
                        "GIT_CONFIG_COUNT": "1",
                        "GIT_CONFIG_KEY_0": "http.extraHeader",
                        "GIT_CONFIG_VALUE_0": f"Authorization: {header}",
                    }
                )
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "protocol.ext.allow=never",
            "-C",
            "/",
            "ls-remote",
            "--",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RemoteRefsError(
                f"ls-remote {_redacted(url)} timed out after {self._timeout:g}s"
            ) from None
        if proc.returncode != 0:
            raise RemoteRefsError(
                f"ls-remote {_redacted(url)} exited {proc.returncode}: "
                f"{stderr.decode(errors='replace')[:200].strip()}"
            )
        return parse_ls_remote(stdout.decode(errors="replace"))


def parse_ls_remote(output: str) -> frozenset[str]:
    """Every object id in ``ls-remote`` output. A malformed line raises."""
    oids: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        oid, sep, _ref = line.partition("\t")
        if not sep or not _OID.match(oid):
            raise RemoteRefsError(f"unexpected ls-remote line {line[:80]!r}")
        oids.add(oid)
    return frozenset(oids)


def _ls_remote_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "SSH_ASKPASS": "/bin/false",
    }


def _redacted(url: str) -> str:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return parsed._replace(netloc=parsed.hostname or "").geturl()
    return url


def github_slug(url: str) -> str | None:
    """``owner/repo`` for an https github.com URL, else None."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return None
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return "/".join(parts)


async def github_app_credential(url: str) -> str | None:
    """A read-only, one-repository App token for a GitHub URL, as a Basic header.

    None for a URL that is not GitHub. Raises when GitHub is named and no token
    can be minted: the caller then cannot prove anything, and keeps the dir.
    """
    slug = github_slug(url)
    if slug is None:
        return None
    from syn_adapters.github.client import get_github_client
    from syn_adapters.github.client_token import installation_token

    client = get_github_client()
    installation_id = await client.get_installation_for_repo(slug)
    token = await installation_token(
        client,
        installation_id,
        permissions={"contents": "read"},
        repositories=[slug.split("/", 1)[1]],
    )
    basic = base64.b64encode(f"x-access-token:{token.token}".encode()).decode()
    return f"Basic {basic}"
