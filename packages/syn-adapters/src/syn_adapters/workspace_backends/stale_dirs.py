"""The host side of reclaiming workspace directories whose container is gone (PC-130).

What the domain guard (`guard_stale_workspace_dir`) cannot do itself: see
which directories exist and which containers still mount them, read their
repositories with git from the host, and ask a remote what it holds
(`GitLsRemote`).

EVERY WALK FAILS CLOSED (#1983). A directory this process cannot list is not
an empty directory: it may hold the only copy of an agent's work, written as
another user. So every ``os.walk`` here passes ``onerror=_raise``, a failed
``lstat`` raises too, and the directory is kept as ``unreadable``.

RUNNING GIT ON A REPOSITORY AN AGENT WROTE. The repository's own config and
layout are the agent's to write, and git runs commands named in the config
(filters, diff drivers, fsmonitor) and follows paths named in the layout
(a `.git` file, `commondir`, alternates, `core.worktree`). This process is
the API, on the host. So a repository is read here only when everything git
would read stays inside the workspace and its config sets nothing outside a
short allowlist (`_ALLOWED_CONFIG`); any other repository is refused
(`UnsafeRepositoryError`), which reports it and keeps the directory. Every
call also disables hooks and fsmonitor, and stops git searching above the
repository. The config is listed under the same trust (`safe.directory=*`)
as every later call: listed without it, git silently drops a different
owner's repository config, the scan sees nothing, and the next call loads
and runs it.

WHAT A REPOSITORY DOES NOT HOLD. A workspace keeps work outside its working
trees too - `artifacts/output`, session spools, a bare clone, a stash, a file
the repository ignores. Bare repositories are guarded like any other; every
other file git cannot reproduce keeps the directory, and only proven caches
(`_is_proven_cache`) are left out of that.
"""

from __future__ import annotations

import asyncio
import os
import posixpath
import re
import socket
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn

from syn_adapters.workspace_backends.orphaned import docker_inspect_raw, parse_inspect
from syn_adapters.workspace_backends.reclaim_delete import (
    AUTH_DIRNAME,
    CLAIM_PREFIX,
    DELETE_PREFIX,
    is_being_deleted,
)

__all__ = ["CLAIM_PREFIX", "DELETE_PREFIX", "is_being_deleted"]


#: Where AW keeps session capture when it is written into the workspace
#: rather than to the `/spool` volume. Its presence anywhere keeps the
#: directory: capture there is the only copy (#1983, design 1.3).
SESSION_STORE_DIRNAME = ".agentic-session-store"


def _raise(error: OSError) -> NoReturn:
    """``os.walk``'s ``onerror``: a directory that cannot be listed stops the walk."""
    raise error


#: The only repository config keys host git is run under, as (section,
#: whether it has a subsection) -> names, or None for any name. They are what
#: clone, init, checkout and submodule write; none of them names a command or
#: a path git reads outside the workspace. `core.worktree` (written for
#: submodules) is a path, so it is admitted only when it is the repository
#: itself (`_refuse_unsafe_config`). Anything else - include.path, includeIf,
#: filter.*, credential.*, core.sshCommand, extensions git may fetch for -
#: refuses the repository, so an unknown key fails closed.
_ALLOWED_CONFIG: dict[tuple[str, bool], frozenset[str] | None] = {
    ("core", False): frozenset(
        {
            "repositoryformatversion",
            "filemode",
            "bare",
            "logallrefupdates",
            "ignorecase",
            "precomposeunicode",
            "worktree",
        }
    ),
    ("remote", True): frozenset({"url", "fetch"}),
    ("branch", True): frozenset({"remote", "merge"}),
    ("submodule", True): frozenset({"url", "active"}),
    ("extensions", False): frozenset({"objectformat"}),
    ("user", False): None,
}

_GIT_GUARD_ARGS = (
    "-c",
    "safe.directory=*",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
)

#: Only `safe.directory`: the config listing must see what later calls load,
#: without echoing our own command-disabling overrides back as findings.
_GIT_TRUST_ARGS = ("-c", "safe.directory=*")

#: The Cache Directory Tagging signature (https://bford.info/cachedir/).
#: Cargo's `target`, pytest, mypy and ruff write it into what they own.
_CACHEDIR_TAG_SIGNATURE = b"Signature: 8a477f597d28d172789f06886806bc55"


def _is_proven_cache(path: Path) -> bool:
    """Whether a directory's contents are shown regenerable by what it holds.

    A name proves nothing - an agent may write its only copy into ``target``
    or ``.cache`` - so each rule reads the directory, not what it is called:
    a CACHEDIR.TAG explicitly designates the contents as disposable. A
    package manifest or virtualenv marker does not prove that every file
    inside can be reproduced: agents may edit installed dependencies.
    """
    if path.is_symlink() or not path.is_dir():
        return False
    return _has_cachedir_tag(path)


def _has_cachedir_tag(path: Path) -> bool:
    try:
        with (path / "CACHEDIR.TAG").open("rb") as tag:
            return tag.read(len(_CACHEDIR_TAG_SIGNATURE)) == _CACHEDIR_TAG_SIGNATURE
    except OSError:
        return False


_GIT_TIMEOUT_SECONDS = 120

#: How deep git follows alternates of alternates; deeper is refused.
_MAX_ALTERNATES_DEPTH = 5


class HostGitError(RuntimeError):
    """Git could not give a definite answer about a repository."""


class UnsafeRepositoryError(HostGitError):
    """A repository host git would follow out of the workspace or run a command for.

    It is not read at all, so nothing it names takes effect; like any
    `HostGitError` it keeps its directory.
    """


@dataclass(frozen=True)
class WorkspaceDirListing:
    """One directory under the workspace base, measured in a single walk."""

    workspace_id: str
    host_dir: str
    size_bytes: int
    #: ``(st_dev, st_ino)`` of the directory itself: a rename keeps it, a
    #: replacement does not.
    identity: tuple[int, int] = (0, 0)
    #: Why some of it could not be read, or None when the walk saw all of it.
    unreadable: str | None = None
    #: Whether a session-store directory exists anywhere inside.
    session_store: bool = False


@dataclass(frozen=True)
class ContainerMounts:
    """One container in any state, of any name, and every mount source it holds."""

    container_id: str
    sources: tuple[str, ...]
    running: bool = False

    def blocks(self, workspace_id: str, host_base: str) -> bool:
        """Whether any source can reach the workspace directory under any of its names.

        Compared as canonical host paths: a source that is the directory (as
        itself, claimed or being deleted), anything inside it, or any
        ANCESTOR of it - the base, its parent, ``/`` - reaches it. Only the
        caller's own container is exempt, and the caller decides that
        (`own_container_id`), not this method.
        """
        base = PurePosixPath(posixpath.normpath(host_base))
        names = (workspace_id, CLAIM_PREFIX + workspace_id, DELETE_PREFIX + workspace_id)
        dirs = [base / name for name in names]
        for raw in self.sources:
            source = PurePosixPath(posixpath.normpath(raw))
            if base == source or base.is_relative_to(source):
                return True
            if any(source == d or source.is_relative_to(d) for d in dirs):
                return True
        return False


def own_container_id() -> str | None:
    """This process's container id prefix, as docker names it in the hostname, or None.

    Docker sets a container's hostname to the first 12 hex digits of its id
    unless compose overrides it (ours does not). Anything else is not a
    container we can name, so nothing is exempt.
    """
    name = socket.gethostname()
    return name if re.fullmatch(r"[0-9a-f]{12}", name) else None


def workspace_id_of(name: str) -> str:
    """The workspace id a base-directory entry stands for, claimed or being deleted."""
    return name.removeprefix(CLAIM_PREFIX).removeprefix(DELETE_PREFIX)


def claim_workspace_dir(host_dir: str) -> str:
    """Rename ``host_dir`` out of its workspace path; return where. Raises ``OSError``.

    The rename is atomic, so the check that follows it is the last word: a
    container or execution arriving later finds no directory to take.
    """
    path = Path(host_dir)
    if path.name.startswith(CLAIM_PREFIX):
        return host_dir
    claimed = path.with_name(CLAIM_PREFIX + path.name)
    if claimed.exists():
        raise FileExistsError(f"{claimed} already exists")
    path.rename(claimed)
    return str(claimed)


def release_workspace_dir(claimed: str) -> None:
    """Put a claimed directory back at its workspace path; a no-op if it is not claimed.

    Whoever claimed it - this pass, or one that died - a kept directory is
    returned, or it would stay claimed forever. Raises ``OSError`` when the
    workspace path was retaken, and the directory then stays claimed.
    """
    path = Path(claimed)
    if not path.name.startswith(CLAIM_PREFIX):
        return
    host_dir = path.with_name(path.name.removeprefix(CLAIM_PREFIX))
    if os.path.lexists(host_dir):
        raise FileExistsError(f"{host_dir} was recreated while it was claimed")
    path.rename(host_dir)


def scan_workspace_dirs(base: str) -> list[WorkspaceDirListing]:
    """Every directory directly under ``base``, sized. Blocking: call off the loop.

    A claimed directory left by a pass that died is listed under its
    workspace id again, so the next pass guards and finishes it.
    """
    root = Path(base)
    if not root.is_dir():
        return []
    listings: list[WorkspaceDirListing] = []
    for entry in sorted(root.iterdir()):
        if entry.name == AUTH_DIRNAME:
            continue  # the reclaimer's own records, never a workspace
        if entry.is_dir() and not entry.is_symlink():
            listings.append(measure_workspace_dir(entry))
    return listings


def measure_workspace_dir(directory: Path) -> WorkspaceDirListing:
    """One directory, sized in a single walk that fails closed. Blocking."""
    stat = directory.lstat()
    size = 0
    session_store = False
    unreadable: str | None = None
    try:
        for dirpath, dirnames, filenames in os.walk(directory, onerror=_raise):
            here = Path(dirpath)
            if SESSION_STORE_DIRNAME in dirnames or SESSION_STORE_DIRNAME in filenames:
                session_store = True
            for name in filenames:
                size += (here / name).lstat().st_size
    except OSError as exc:
        unreadable = f"{type(exc).__name__}: {exc}"
    return WorkspaceDirListing(
        workspace_id=workspace_id_of(directory.name),
        host_dir=str(directory),
        size_bytes=size,
        identity=(stat.st_dev, stat.st_ino),
        unreadable=unreadable,
        session_store=session_store,
    )


async def list_containers() -> list[ContainerMounts]:
    """Every container on the host, any name, any state, with its mount sources.

    Raises when any of them cannot be read: a container whose mounts are
    unknown may bind any directory, which must then be left alone.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "-a",
        "-q",
        "--no-trunc",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"docker ps -a exited {proc.returncode}")
    containers: list[ContainerMounts] = []
    for container_id in stdout.decode().split():
        raw = await docker_inspect_raw(container_id)
        inspected = parse_inspect(raw) if raw is not None else None
        if inspected is None or inspected.mount_sources is None:
            raise RuntimeError(f"could not inspect container {container_id}")
        containers.append(
            ContainerMounts(container_id, inspected.mount_sources, running=inspected.running)
        )
    return containers


class SubprocessHostWorkspaceGit:
    """`HostWorkspaceGit` over the host's ``git`` binary."""

    async def repositories(self, host_dir: str) -> list[str]:
        """Raises `UnsafeRepositoryError` for one that reads outside ``host_dir``.

        Or whose config is not allowlisted. Every repository is checked before
        any is read: a superproject's diff runs git inside its submodules,
        under their config, which its own check never saw.
        """
        repos = await asyncio.to_thread(_find_repositories, host_dir)
        for repo in repos:
            await self._refuse_unsafe_config(repo)
        return repos

    async def has_stash(self, repo: str) -> bool:
        await self._refuse_unsafe_config(repo)
        out = await _git(repo, "for-each-ref", "--format=%(objectname)", "refs/stash")
        return bool(out.strip())

    async def is_dirty(self, repo: str) -> bool:
        await self._refuse_unsafe_config(repo)
        if _is_bare(repo):
            return False
        index_entries = await _git(repo, "ls-files", "-v", "-z")
        if any(
            entry[:1] == b"S" or entry[:1].islower()
            for entry in index_entries.split(b"\0")
            if entry
        ):
            raise HostGitError(f"{repo} has index flags that can hide authored changes")
        # Each submodule is read as its own repository; `dirty` keeps git
        # from running inside it to ask.
        no_drivers = ("--no-ext-diff", "--no-textconv", "--ignore-submodules=dirty")
        if await _git(
            repo, "diff", *no_drivers, "--cached", "--quiet", ok_codes=(0, 1), status=True
        ):
            return True
        if await _git(repo, "diff", *no_drivers, "--quiet", ok_codes=(0, 1), status=True):
            return True
        untracked = await _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
        return bool(untracked.strip(b"\0"))

    async def unproven_commits(self, repo: str, advertised: frozenset[str]) -> int:
        """Authored commits no advertised object reaches. Reflogs and dangling commits count.

        A commit reset, amended or rebased away is still the agent's work while
        a reflog or the object store holds it, so every reflog entry
        (``--reflog``) is a tip too; anything unreachable altogether keeps the
        directory on its own (`unreachable_objects`).
        Replacement refs are off on every call (``GIT_NO_REPLACE_OBJECTS``),
        and a repository with grafts is refused: both rewrite ancestry, which
        is the very thing this proves. A shallow boundary only removes
        parents, so it can make a walk count more, never less.
        """
        await self._refuse_unsafe_config(repo)
        _refuse_grafts(repo)
        tips = await self._local_tips(repo)
        # Only an advertised object this repository holds can bound the walk;
        # one it lacks proves nothing about what is local.
        held = await self._held_commits(repo, advertised)
        stdin = "".join(f"{tip}\n" for tip in tips) + "".join(f"^{oid}\n" for oid in held)
        out = await _git(repo, "rev-list", "--count", "--reflog", "--stdin", stdin=stdin.encode())
        return int(out.strip() or b"0")

    async def unreachable_objects(self, repo: str) -> int:
        """Every object of any type no ref or reflog reaches (``git fsck --unreachable``).

        A deleted branch, an expired reflog, a blob ``git add`` wrote and a
        reset dropped: none is proven anywhere, so any one of them counts.
        """
        await self._refuse_unsafe_config(repo)
        out = await _git(repo, "fsck", "--unreachable", "--no-progress")
        return sum(
            1
            for line in out.decode(errors="replace").splitlines()
            if line.startswith("unreachable ")
        )

    async def has_submodule_store(self, repo: str) -> bool:
        git_dir = Path(repo) if _is_bare(repo) else _git_dir(Path(repo))
        modules = git_dir / "modules"
        return modules.is_dir() and any(modules.iterdir())

    async def _local_tips(self, repo: str) -> list[str]:
        """HEAD and every ref outside ``refs/remotes/``: what the agent could have made."""
        refs = await _git(repo, "for-each-ref", "--format=%(objectname) %(refname)")
        tips: set[str] = set()
        for line in refs.decode(errors="surrogateescape").splitlines():
            oid, _, name = line.partition(" ")
            if oid and not name.startswith("refs/remotes/"):
                tips.add(oid)
        head = await _git(repo, "rev-parse", "--verify", "-q", "HEAD", ok_codes=(0, 1))
        if head.strip():
            tips.add(head.decode().strip())
        return sorted(tips)

    async def _held_commits(self, repo: str, advertised: frozenset[str]) -> list[str]:
        if not advertised:
            return []
        query = "".join(f"{oid}\n" for oid in sorted(advertised)).encode()
        out = await _git(repo, "cat-file", "--batch-check", stdin=query)
        held: list[str] = []
        for line in out.decode(errors="replace").splitlines():
            oid, _, kind = line.partition(" ")
            if kind.split(" ", 1)[0] in {"commit", "tag"}:
                held.append(oid)
        return held

    async def unversioned_paths(self, host_dir: str, repos: list[str]) -> list[str]:
        ignored: list[str] = []
        for repo in repos:
            if _is_bare(repo):
                continue
            await self._refuse_unsafe_config(repo)
            out = await _git(
                repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"
            )
            ignored.extend(
                str(Path(repo) / name.rstrip("/"))
                for name in out.decode(errors="surrogateescape").split("\0")
                if name
            )
        return await asyncio.to_thread(_list_unversioned, host_dir, repos, ignored)

    async def _refuse_unsafe_config(self, repo: str) -> None:
        # Under the trust later calls use, but without our command-disabling
        # overrides; `--show-scope` tells the one we do pass apart. Included
        # files are listed as their includer's scope, and `include.path`
        # itself is refused.
        config = await _git(
            repo, "config", "--list", "--name-only", "--show-scope", "-z", overrides=_GIT_TRUST_ARGS
        )
        # With -z, scope and name are each NUL-terminated: alternate fields.
        # A stray field raises, which keeps the directory.
        fields = config.decode(errors="replace").split("\0")[:-1]
        keys = [
            key.lower()
            for scope, key in zip(fields[0::2], fields[1::2], strict=True)
            if scope != "command"
        ]
        for key in keys:
            if not _is_allowed_config(key):
                raise UnsafeRepositoryError(
                    f"{repo} sets {key}, which is not on the host-git allowlist; not read"
                )
        if "core.worktree" in keys and (_is_bare(repo) or not await _is_own_worktree(repo)):
            raise UnsafeRepositoryError(f"{repo} has a core.worktree other than itself; not read")


async def _is_own_worktree(repo: str) -> bool:
    top = await _git(repo, "rev-parse", "--show-toplevel")
    return Path(top.decode(errors="surrogateescape").strip()).resolve() == Path(repo).resolve()


def _is_allowed_config(key: str) -> bool:
    section, _, rest = key.partition(".")
    subsection, _, name = rest.rpartition(".")
    if (section, bool(subsection)) not in _ALLOWED_CONFIG:
        return False
    names = _ALLOWED_CONFIG[(section, bool(subsection))]
    return names is None or name in names


def _find_repositories(host_dir: str) -> list[str]:
    root = Path(host_dir).resolve()
    repos: list[str] = []
    for dirpath, dirnames, filenames in os.walk(host_dir, onerror=_raise):
        if _looks_bare(dirpath, dirnames, filenames):
            # A bare clone holds refs no working tree shows; guard it, and do
            # not walk into its object store.
            _refuse_outside(Path(dirpath), Path(dirpath), root)
            repos.append(dirpath)
            dirnames.clear()
            continue
        if ".git" in dirnames or ".git" in filenames:
            _refuse_outside(Path(dirpath), _git_dir(Path(dirpath)), root)
            repos.append(dirpath)
        if ".git" in dirnames:
            dirnames.remove(".git")
    return repos


def _git_dir(repo: Path) -> Path:
    """Where ``repo``'s ``.git`` leads: itself, or the target of a ``gitdir:`` file."""
    dot_git = repo / ".git"
    if not dot_git.is_file():
        return dot_git
    try:
        pointer = dot_git.read_text(errors="surrogateescape")
    except OSError as exc:
        raise UnsafeRepositoryError(f"{dot_git} cannot be read") from exc
    if not pointer.startswith("gitdir: "):
        raise UnsafeRepositoryError(f"{dot_git} is not a gitdir pointer")
    return repo / pointer.removeprefix("gitdir: ").strip()


def _refuse_outside(repo: Path, git_dir: Path, root: Path) -> None:
    """Raise unless the git dir, and every path it hands on, is under ``root``.

    `commondir` (a linked worktree) and `objects/info/alternates` are read by
    every command, so they are confined like the git dir itself. Git follows
    alternates of alternates, so they are confined at every depth.
    """
    git_dir = _confined(repo, git_dir.resolve(), root)
    common = git_dir
    if (git_dir / "commondir").is_file():
        common = (git_dir / (git_dir / "commondir").read_text().strip()).resolve()
        _confined(repo, common, root)
    _refuse_alternates_outside(repo, common / "objects", root)


def _refuse_alternates_outside(repo: Path, start: Path, root: Path) -> None:
    """Confine every alternate git would follow from ``start``, at every depth."""
    pending = [(start, 0)]
    seen: set[Path] = set()
    while pending:
        objects, depth = pending.pop()
        alternates = objects / "info" / "alternates"
        if objects in seen or not alternates.is_file():
            continue
        seen.add(objects)
        if depth >= _MAX_ALTERNATES_DEPTH:
            raise UnsafeRepositoryError(f"{repo} chains alternates past {depth}; not read")
        # Each entry is relative to the objects directory whose file names it.
        pending.extend(
            (_confined(repo, (objects / entry).resolve(), root), depth + 1)
            for entry in _alternate_entries(repo, alternates)
        )


def _alternate_entries(repo: Path, alternates: Path) -> list[str]:
    entries: list[str] = []
    for line in alternates.read_text(errors="surrogateescape").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith('"'):
            raise UnsafeRepositoryError(f"{repo} has a quoted alternate; not read")
        entries.append(line.strip())
    return entries


def _confined(repo: Path, path: Path, root: Path) -> Path:
    if not path.is_relative_to(root):
        raise UnsafeRepositoryError(f"{repo} reads {path}, outside the workspace; not read")
    return path


def _looks_bare(dirpath: str, dirnames: list[str], filenames: list[str]) -> bool:
    return (
        "HEAD" in filenames
        and "objects" in dirnames
        and "refs" in dirnames
        and Path(dirpath).name != ".git"
    )


def _refuse_grafts(repo: str) -> None:
    git_dir = Path(repo) if _is_bare(repo) else _git_dir(Path(repo))
    if (git_dir / "info" / "grafts").exists():
        raise UnsafeRepositoryError(f"{repo} has grafts, which rewrite ancestry; not proven")


#: What git itself keeps in a git directory. Anything else there - a
#: ``recovery.patch`` in a bare clone, notes in ``.git`` - is no repository's
#: content and keeps the directory. In-progress operations (``MERGE_HEAD``,
#: ``rebase-merge``, ``sequencer``) and LFS objects are deliberately absent:
#: they are unfinished or unpushed work.
_GIT_METADATA = frozenset(
    {
        "HEAD",
        "ORIG_HEAD",
        "FETCH_HEAD",
        "COMMIT_EDITMSG",
        "config",
        "description",
        "hooks",
        "info",
        "objects",
        "refs",
        "packed-refs",
        "logs",
        "index",
        "branches",
        "modules",
        "worktrees",
        "shallow",
        "commondir",
        "gitdir",
    }
)


def _unrecognized_git_metadata(git_dir: Path, root: Path) -> list[Path]:
    """Entries of a git directory git does not put there; hooks other than samples."""
    if not git_dir.is_dir() or not git_dir.resolve().is_relative_to(root.resolve()):
        return []
    found = [entry for entry in git_dir.iterdir() if entry.name not in _GIT_METADATA]
    hooks = git_dir / "hooks"
    if hooks.is_dir() and not hooks.is_symlink():
        found.extend(h for h in hooks.iterdir() if not h.name.endswith(".sample"))
    return found


def _is_bare(repo: str) -> bool:
    return not (Path(repo) / ".git").exists()


def _list_unversioned(host_dir: str, repos: list[str], ignored: list[str]) -> list[str]:
    """Every file git cannot reproduce, relative to ``host_dir``, sorted.

    Everything outside every repository, plus each repository's ignored files,
    less proven caches. Raises ``OSError`` when any part cannot be listed.
    """
    root = Path(host_dir)
    repo_roots = {Path(r) for r in repos}
    members = _unversioned_under(root, repo_roots)
    for repo in repos:
        git_dir = Path(repo) if _is_bare(repo) else _git_dir(Path(repo))
        members.extend(_unrecognized_git_metadata(git_dir, root))
    for name in ignored:
        path = Path(name)
        relative = path.relative_to(root).parts
        if not any(
            _is_proven_cache(root.joinpath(*relative[: i + 1])) for i in range(len(relative))
        ):
            members.extend(_unversioned_under(path, repo_roots))
    return sorted({str(member.relative_to(root)) for member in members})


def _unversioned_under(path: Path, repo_roots: set[Path]) -> list[Path]:
    """``path`` itself if a file, else every file below it outside ``repo_roots`` and caches."""
    if path.is_symlink() or path.is_file():
        return [path]
    members: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(path, onerror=_raise):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames if here / d not in repo_roots and not _is_proven_cache(here / d)
        ]
        members.extend(here / f for f in filenames)
        members.extend(here / d for d in dirnames if (here / d).is_symlink())
    return members


def _git_env(repo: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        # Replacement refs rewrite what an object id means; never honour them.
        "GIT_NO_REPLACE_OBJECTS": "1",
        # `repo` was found as a repository; never let git search above it for
        # another one, which may be outside the workspace.
        "GIT_CEILING_DIRECTORIES": str(Path(repo).resolve().parent),
    }


async def _git(
    repo: str,
    *args: str,
    ok_codes: tuple[int, ...] = (0,),
    overrides: tuple[str, ...] = _GIT_GUARD_ARGS,
    status: bool = False,
    stdin: bytes | None = None,
) -> bytes:
    """Stdout, or with ``status`` b"1" when git exited non-zero and b"" when zero."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *overrides,
        "-C",
        repo,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
        env=_git_env(repo),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin), timeout=_GIT_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise HostGitError(f"git {args[0]} timed out in {repo}") from None
    if proc.returncode not in ok_codes:
        raise HostGitError(
            f"git {args[0]} exited {proc.returncode} in {repo}: "
            f"{stderr.decode(errors='replace')[:300].strip()}"
        )
    if status:
        return b"1" if proc.returncode else b""
    return stdout
