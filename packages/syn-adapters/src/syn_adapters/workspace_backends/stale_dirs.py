"""The host side of reclaiming workspace directories whose container is gone (PC-130).

Three things the domain guard (`guard_stale_workspace_dir`) cannot do itself:
see which directories exist and which containers still mount them, read their
repositories with git from the host, and archive a dirty tree to MinIO.

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
other file git cannot reproduce is archived as one tarball, and only proven
caches (`_is_proven_cache`) are left out of it.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.orphaned import docker_inspect_raw, parse_inspect

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import StaleWorkspaceDir

#: A patch larger than this is not archived, so its directory is kept: a
#: tree that big is not "a few uncommitted edits", and an operator decides.
MAX_PATCH_BYTES = 100 * 1024 * 1024

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
    #: Newest mtime of anything inside, epoch seconds: the grace clock.
    last_modified: float


@dataclass(frozen=True)
class WorkspaceContainer:
    """A workspace container in any state, by the directory it mounts."""

    workspace_id: str
    execution_id: str | None
    running: bool


#: A directory claimed for deletion is renamed to this prefix plus its
#: workspace id, so no owner can reach it at its workspace path any more.
CLAIM_PREFIX = ".reclaiming-"


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


def release_workspace_dir(claimed: str, host_dir: str) -> None:
    """Put a claimed directory back. Raises ``OSError`` when its path was retaken."""
    if claimed == host_dir:
        return
    if Path(host_dir).exists():
        raise FileExistsError(f"{host_dir} was recreated while it was claimed")
    Path(claimed).rename(host_dir)


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
        if entry.is_dir() and not entry.is_symlink():
            size, newest = _measure(entry)
            listings.append(
                WorkspaceDirListing(
                    workspace_id=entry.name.removeprefix(CLAIM_PREFIX),
                    host_dir=str(entry),
                    size_bytes=size,
                    last_modified=newest,
                )
            )
    return listings


def _measure(directory: Path) -> tuple[int, float]:
    size = 0
    newest = directory.lstat().st_mtime
    for dirpath, dirnames, filenames in os.walk(directory):
        here = Path(dirpath)
        # Git's own bookkeeping is not work: reading a repository refreshes
        # its index, and that must not read as "changed during archival".
        # Git state is compared separately (`WorkspaceDirReclaimer._git_state`).
        bookkeeping = ".git" in here.relative_to(directory).parts
        for name, is_file in (*((d, False) for d in dirnames), *((f, True) for f in filenames)):
            try:
                stat = (here / name).lstat()
            except OSError:
                continue
            if not bookkeeping and name != ".git":
                newest = max(newest, stat.st_mtime)
            if is_file:
                size += stat.st_size
    return size, newest


async def list_workspace_containers() -> list[WorkspaceContainer]:
    """Every ``agentic-ws-`` container, stopped ones included.

    Raises when any of them cannot be read: a container whose state is unknown
    may be running, and its directory must then be left alone.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "-a",
        "-q",
        "--filter",
        "name=agentic-ws-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"docker ps -a exited {proc.returncode}")
    containers: list[WorkspaceContainer] = []
    for container_id in stdout.decode().split():
        raw = await docker_inspect_raw(container_id)
        inspected = parse_inspect(raw) if raw is not None else None
        if inspected is None:
            raise RuntimeError(f"could not inspect workspace container {container_id}")
        if inspected.workspace_source is None:
            continue
        containers.append(
            WorkspaceContainer(
                workspace_id=Path(inspected.workspace_source).name,
                execution_id=inspected.labels.get("syn.execution_id") or None,
                running=inspected.running,
            )
        )
    return containers


class SubprocessHostWorkspaceGit:
    """`HostWorkspaceGit` over the host's ``git`` binary."""

    async def repositories(self, host_dir: str) -> list[str]:
        """Raises `UnsafeRepositoryError` for one that reads outside ``host_dir``."""
        return await asyncio.to_thread(_find_repositories, host_dir)

    async def unpushed_commits(self, repo: str) -> int:
        await self._refuse_unsafe_config(repo)
        # Every ref (branches, tags, stash) and HEAD: an agent on a detached
        # HEAD commits too, and a stash is work no branch reaches.
        out = await _git(repo, "rev-list", "--count", "--all", "HEAD", "--not", "--remotes")
        return int(out.strip() or b"0")

    async def uncommitted_patch(self, repo: str) -> bytes:
        await self._refuse_unsafe_config(repo)
        if _is_bare(repo):
            return b""
        index_entries = await _git(repo, "ls-files", "-v", "-z")
        if any(
            entry[:1] == b"S" or entry[:1].islower()
            for entry in index_entries.split(b"\0")
            if entry
        ):
            raise HostGitError(f"{repo} has index flags that can hide authored changes")
        diff_args = ("--binary", "--no-ext-diff", "--no-textconv", "--no-color")
        # A HEAD-to-tree patch holds one state. When the index differs from
        # both HEAD and the tree, the staged state would be lost: keep it.
        staged = await _git(
            repo,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--cached",
            "--quiet",
            ok_codes=(0, 1),
            status=True,
        )
        unstaged = await _git(
            repo, "diff", "--no-ext-diff", "--no-textconv", "--quiet", ok_codes=(0, 1), status=True
        )
        if staged and unstaged:
            raise HostGitError(f"{repo} has staged changes the working tree no longer matches")
        patch = await _git(repo, "diff", *diff_args, "HEAD")
        untracked = await _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
        for name in filter(None, untracked.decode(errors="surrogateescape").split("\0")):
            # Exit 1 is "they differ", which for /dev/null is always.
            patch += await _git(
                repo, "diff", "--no-index", *diff_args, "--", "/dev/null", name, ok_codes=(0, 1)
            )
            if len(patch) > MAX_PATCH_BYTES:
                raise HostGitError(f"uncommitted changes in {repo} exceed {MAX_PATCH_BYTES} bytes")
        if len(patch) > MAX_PATCH_BYTES:
            raise HostGitError(f"uncommitted changes in {repo} exceed {MAX_PATCH_BYTES} bytes")
        return patch

    async def unversioned_files(self, host_dir: str, repos: list[str]) -> bytes:
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
        return await asyncio.to_thread(_tar_unversioned, host_dir, repos, ignored)

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
    for dirpath, dirnames, filenames in os.walk(host_dir):
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
    every command, so they are confined like the git dir itself.
    """
    git_dir = git_dir.resolve()
    reads = [git_dir]
    common = git_dir
    if (git_dir / "commondir").is_file():
        common = (git_dir / (git_dir / "commondir").read_text().strip()).resolve()
        reads.append(common)
    alternates = common / "objects" / "info" / "alternates"
    if alternates.is_file():
        reads.extend(
            (common / "objects" / line.strip()).resolve()
            for line in alternates.read_text(errors="surrogateescape").splitlines()
            if line.strip() and not line.startswith("#")
        )
    for path in reads:
        if not path.is_relative_to(root):
            raise UnsafeRepositoryError(f"{repo} reads {path}, outside the workspace; not read")


def _looks_bare(dirpath: str, dirnames: list[str], filenames: list[str]) -> bool:
    return (
        "HEAD" in filenames
        and "objects" in dirnames
        and "refs" in dirnames
        and Path(dirpath).name != ".git"
    )


def _is_bare(repo: str) -> bool:
    return not (Path(repo) / ".git").exists()


def _tar_unversioned(host_dir: str, repos: list[str], ignored: list[str]) -> bytes:
    """A gzipped tar of what git cannot reproduce, or b"" when there is none.

    Everything outside every repository, plus each repository's ignored files,
    less proven caches. Raises `HostGitError` past `MAX_PATCH_BYTES`.
    """
    root = Path(host_dir)
    repo_roots = {Path(r) for r in repos}
    members = _unversioned_under(root, repo_roots)
    for name in ignored:
        path = Path(name)
        relative = path.relative_to(root).parts
        if not any(
            _is_proven_cache(root.joinpath(*relative[: i + 1])) for i in range(len(relative))
        ):
            members.extend(_unversioned_under(path, repo_roots))
    if not members:
        return b""
    return _write_tar(root, sorted(set(members)))


def _unversioned_under(path: Path, repo_roots: set[Path]) -> list[Path]:
    """``path`` itself if a file, else every file below it outside ``repo_roots`` and caches."""
    if path.is_symlink() or path.is_file():
        return [path]
    members: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(path):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames if here / d not in repo_roots and not _is_proven_cache(here / d)
        ]
        members.extend(here / f for f in filenames)
        members.extend(here / d for d in dirnames if (here / d).is_symlink())
    return members


def _write_tar(root: Path, members: list[Path]) -> bytes:
    total = 0
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for member in members:
            total += member.lstat().st_size
            if total > MAX_PATCH_BYTES:
                raise HostGitError(f"unversioned files in {root} exceed {MAX_PATCH_BYTES} bytes")
            tar.add(member, arcname=str(member.relative_to(root)), recursive=False)
    return buffer.getvalue()


async def _git(
    repo: str,
    *args: str,
    ok_codes: tuple[int, ...] = (0,),
    overrides: tuple[str, ...] = _GIT_GUARD_ARGS,
    status: bool = False,
) -> bytes:
    """Stdout, or with ``status`` b"1" when git exited non-zero and b"" when zero."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        # `repo` was found as a repository; never let git search above it for
        # another one, which may be outside the workspace.
        "GIT_CEILING_DIRECTORIES": str(Path(repo).resolve().parent),
    }
    proc = await asyncio.create_subprocess_exec(
        "git",
        *overrides,
        "-C",
        repo,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT_SECONDS)
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


def archive_key(stale: StaleWorkspaceDir, path: str) -> str:
    """A key unique per (workspace, path): readable slug plus a hash of the exact path.

    The slug alone is not injective (``a_b`` and ``a/b`` meet), and an object
    store overwrites on a repeated key.
    """
    relative = str(Path(path).relative_to(stale.host_dir))
    slug = relative.replace(os.sep, "_").strip("._") or "root"
    digest = hashlib.sha256(relative.encode(errors="surrogateescape")).hexdigest()[:16]
    return f"reclaimed-{stale.workspace_id}-{slug}-{digest}"


class ArtifactStoragePatchArchive:
    """`PatchArchive` over the artifact bucket, keyed under the execution."""

    async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
        from syn_adapters.storage.artifact_storage.factory import get_artifact_storage

        storage = await get_artifact_storage()
        result = await storage.upload(
            archive_key(stale, repo),
            patch,
            execution_id=stale.execution_id,
            content_type="text/x-diff",
            metadata={"reclaimed_from": stale.host_dir, "repository": repo},
        )
        return result.storage_uri

    async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
        from syn_adapters.storage.artifact_storage.factory import get_artifact_storage

        storage = await get_artifact_storage()
        result = await storage.upload(
            f"{archive_key(stale, stale.host_dir)}-files",
            tarball,
            execution_id=stale.execution_id,
            content_type="application/gzip",
            metadata={"reclaimed_from": stale.host_dir},
        )
        return result.storage_uri
