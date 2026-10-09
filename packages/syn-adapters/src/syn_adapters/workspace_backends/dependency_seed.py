"""Warm dependency caches copied into a workspace instead of installing from cold (#1714).

Every workspace's uv and pnpm caches live inside it (`/workspace/.cache`, see
`agentic.adapter._WORKSPACE_CACHE_ENV`), so every phase downloads and builds
its dependencies again. That is inferred to be the largest CPU and disk cost
of a run (#1714, step 6 of the #1310 capacity plan).

A SEED is a uv or pnpm cache the platform built for one lockfile. It is keyed
by (tool, repository, sha256 of the lockfile), so a lockfile that changes by
one byte never reuses a stale seed: it misses, and the workspace installs as
it always did.

THE SEED IS NEVER SHARED WRITABLY. #1310 rejected a shared writable cache: one
agent could plant a poisoned wheel that every later run installs. So:

- a seed is produced only by the platform's own download-only command
  (`WARM_COMMANDS`), run BEFORE any agent has run in that workspace, in a
  scratch directory the platform fills with the lockfile and nothing of the
  checkout's but `WARM_MANIFESTS`, and published from the cache that command
  alone wrote. No other file of the checkout (a `.venv`, a `uv.toml`, a
  pnpmfile, an `.npmrc`) is present to be run or read. A workspace's cache is
  never read back into the store once an agent has run;
- a workspace never sees the store. `seed` COPIES a seed into the workspace's
  own writable cache from the host side, through the workspace directory the
  host bind-mounts at `/workspace`, so the agent can corrupt its own copy and
  nothing else;
- the store is made read-only on disk once published.

The only thing read from a workspace is its lockfile, and only to hash it, to
choose which seed to copy. A lockfile that is not a regular file (a symlink a
repository could point anywhere on the host) is not read.

Retention is LRU by the time a seed was last copied, under one byte budget
(`SYN_DEPENDENCY_SEED_MAX_BYTES`), so the store cannot grow without bound.
Every `seed` and every `publish` prunes, so a store a burst of publications
left over budget converges once the grace expires, even if only cache hits
follow. A copy holds a shared lease on its seed (`_seed_lease`) and a prune
deletes only under an exclusive one, so a seed is never deleted mid-copy.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import logging
import os
import re
import shutil
import stat
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

logger = logging.getLogger(__name__)

#: Each seeded tool, and the lockfile whose hash keys its seed. The cache it
#: seeds is `/workspace/.cache/<tool>`, which is where
#: `agentic.adapter._WORKSPACE_CACHE_ENV` points that tool.
SEEDED_TOOLS: Final[dict[str, str]] = {"uv": "uv.lock", "pnpm": "pnpm-lock.yaml"}

#: The checkout's files, besides the lockfile, a warm cannot do without. Only
#: these are copied into the scratch directory a warm runs in.
#:
#: THE CHECKOUT IS NOT TRUSTED. A verify phase checks out what an implement
#: phase's agent pushed, so every file in it but the lockfile's hashes may be
#: an agent's. A warm run IN the checkout runs that agent's code: uv executes
#: the checkout's `.venv/bin/python` and reads its `uv.toml`, and pnpm runs its
#: `.pnpmfile.*` (both reproduced in #1802's verification). That code could
#: write into the cache being built, which would be served to every later run
#: with the same lockfile, including runs on main.
#:
#: uv needs the root `pyproject.toml` to find the project; it is read as data,
#: and with `--frozen` what is downloaded, and its hashes, come from the lock.
#: `pnpm fetch` is built to run from the lockfile alone.
WARM_MANIFESTS: Final[dict[str, tuple[str, ...]]] = {"uv": ("pyproject.toml",), "pnpm": ()}

#: How the platform builds each tool's seed, in that scratch directory. Each
#: command downloads only what the lockfile pins, verified against the
#: lockfile's hashes, and runs nothing:
#:
#: - `uv sync --no-install-workspace --no-install-local` builds no project of
#:   the repository's own, and `--no-build` builds no sdist at all, so no build
#:   backend runs. A lockfile that needs an sdist fails to warm and the run
#:   goes on cold;
#: - `pnpm fetch` runs no lifecycle scripts, and `--ignore-pnpmfile` keeps it
#:   from loading a pnpmfile even if one were present.
#:
#: A malicious lockfile is not a way in: its seed is keyed by its own hash, so
#: it reaches only runs that would install that lockfile anyway.
WARM_COMMANDS: Final[dict[str, tuple[str, ...]]] = {
    "uv": (
        "uv",
        "sync",
        "--frozen",
        "--no-install-workspace",
        "--no-install-local",
        "--no-build",
    ),
    # No `--frozen-lockfile`: `fetch` only ever reads the lockfile, and pnpm 12
    # rejects the flag there.
    "pnpm": ("pnpm", "fetch", "--ignore-pnpmfile"),
}

#: Set for every warm. `UV_NO_CONFIG` ignores any `uv.toml` above the scratch
#: directory; the scratch directory's own `.venv` is named explicitly so uv
#: can never pick up an environment the checkout shipped.
_WARM_ENVIRONMENT: Final[dict[str, str]] = {"UV_NO_CONFIG": "1"}

#: A warm that has not finished by then is abandoned and the run goes on cold.
_WARM_TIMEOUT_SECONDS: Final = 900

#: A seed copied or published less than this long ago is never pruned, even
#: over budget, so a seed a burst of runs is about to reuse is not thrashed
#: out and rebuilt. It is NOT what protects a copy in flight: the lease is.
_PRUNE_GRACE_SECONDS: Final = 3600

#: A GitHub ``owner/name``. Checked because it becomes two path components of
#: the store, and ``..`` there would name a directory outside it.
_REPOSITORY_RE: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class SeedKey:
    """Which seed a workspace needs: one tool's cache for one exact lockfile."""

    tool: str
    repository: str
    lockfile_sha256: str

    def __post_init__(self) -> None:
        if not _REPOSITORY_RE.fullmatch(self.repository) or ".." in self.repository:
            raise ValueError(f"Not an owner/name repository: {self.repository!r}")

    @property
    def relative_path(self) -> Path:
        return Path(self.tool, self.repository, self.lockfile_sha256)


def seed_keys(repository: str, clone_dir: Path) -> list[SeedKey]:
    """The seeds a clone of ``repository`` at ``clone_dir`` would use, one per lockfile."""
    keys: list[SeedKey] = []
    for tool, lockfile in SEEDED_TOOLS.items():
        path = clone_dir / lockfile
        # lstat, not exists(): a symlinked lockfile is the repository's choice
        # of what the host reads, so it is not read at all.
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
        except FileNotFoundError:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        keys.append(SeedKey(tool, repository, digest))
    return keys


@dataclass
class SeedOutcome:
    """What `DependencySeedStore.seed` did for one workspace."""

    copied: list[SeedKey] = field(default_factory=list)
    #: Seeds the store lacks, with the checkout whose lockfile names each.
    missing: list[tuple[SeedKey, Path]] = field(default_factory=list)


class DependencySeedStore:
    """Platform-owned seeds on the host, copied into workspaces and pruned LRU."""

    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self._root = root
        self._max_bytes = max_bytes

    def seed(self, workspace_dir: Path, clones: Iterable[tuple[str, Path]]) -> SeedOutcome:
        """Copy every ready seed for ``clones`` into ``workspace_dir``'s caches.

        ``workspace_dir`` is the host side of `/workspace`; each clone is
        ``(repository, host path of its checkout)``. A seed the store does not
        have is reported missing, not raised: that workspace installs cold.

        A copy that fails partway removes the whole of that tool's cache from
        the workspace, so it installs cold rather than from half a seed.

        Ends with a `prune`: a cache hit is the only event a store that is
        over budget may ever see again.
        """
        outcome = SeedOutcome()
        for repository, clone_dir in clones:
            for key in seed_keys(repository, clone_dir):
                self._seed_one(key, clone_dir, workspace_dir / ".cache" / key.tool, outcome)
        try:
            self.prune()
        except OSError:
            logger.exception("Could not prune the dependency seed store %s", self._root)
        return outcome

    def _seed_one(
        self, key: SeedKey, clone_dir: Path, destination: Path, outcome: SeedOutcome
    ) -> None:
        source = self._root / key.relative_path
        try:
            with _seed_lease(source, exclusive=False):
                # Checked under the lease: a prune may have deleted the seed
                # between any earlier look and taking it.
                if not source.is_dir():
                    outcome.missing.append((key, clone_dir))
                    return
                # Touched under the lease, so a prune waiting on it re-reads
                # this as the seed's LRU clock before deciding.
                os.utime(source)
                _copy_writable(source, destination)
        except OSError:
            logger.exception("Could not copy dependency seed %s; installing cold", _label(key))
            # The destination is fresh (no agent has run yet), so all of it
            # goes, including any earlier clone's seed for the same tool.
            shutil.rmtree(destination, ignore_errors=True)
            outcome.copied = [copied for copied in outcome.copied if copied.tool != key.tool]
            return
        outcome.copied.append(key)

    def publish(self, key: SeedKey, built_cache: Path) -> None:
        """Install a cache THE PLATFORM built as the seed for ``key``, then prune.

        Never call this with anything an agent workspace wrote: that is the
        shared writable cache #1310 rejected, one step removed. The cache must
        have been built at the same in-container path a workspace uses
        (`/workspace/.cache/<tool>`): uv's cache holds absolute symlinks.

        ``built_cache`` is copied into a staging directory, which is then
        renamed into place, so a reader sees either no seed or the whole of one.
        """
        target = self._root / key.relative_path
        staging = target.parent / f".staging-{uuid.uuid4().hex}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built_cache, staging, symlinks=True)
        # copytree carries the source's mtime over, and mtime is the LRU clock:
        # without this a seed published a moment ago could be pruned first.
        os.utime(staging)
        size = _size(staging)
        _make_read_only(staging)
        # Recorded once here, so a prune on every cache hit reads one small
        # file per seed instead of walking every file of every seed.
        _write_size(target, size)
        try:
            staging.rename(target)
        except OSError:
            # Another warmer published the same lockfile first; theirs is as good.
            _remove(staging)
        self.prune()

    def prune(self) -> int:
        """Delete least recently copied seeds until the store fits its budget.

        Returns the bytes freed. A seed copied within the grace period is kept
        even over budget, so a burst does not thrash. A seed being copied
        right now is kept whatever its age: its lease is held, and a seed is
        deleted only under an exclusive lease, after re-reading its LRU clock.
        """
        seeds = sorted(
            (path.stat().st_mtime, path, _recorded_size(path))
            for path in self._root.glob("*/*/*/*")
            # Staging directories too: one a crashed publish left behind is
            # otherwise never deleted. A live one is inside the grace.
            if path.is_dir()
        )
        remaining = sum(size for _, _, size in seeds)
        freed = 0
        cutoff = time.time() - _PRUNE_GRACE_SECONDS
        for snapshot_mtime, path, size in seeds:
            # mtimes only move forward, so nothing after this is past the grace.
            if remaining <= self._max_bytes or snapshot_mtime > cutoff:
                break
            try:
                with _seed_lease(path, exclusive=True, blocking=False):
                    # Re-read under the lease: a copy may have touched the
                    # seed since the snapshot this loop is sorted by.
                    try:
                        mtime = path.stat().st_mtime
                    except FileNotFoundError:
                        remaining -= size  # another prune got there first
                        continue
                    if mtime > cutoff:
                        continue
                    _remove(path)
                    _sidecar(path, ".size").unlink(missing_ok=True)
            except BlockingIOError:
                continue  # being copied right now, so not least recently used
            remaining -= size
            freed += size
            logger.info("Pruned dependency seed %s (%d bytes)", path, size)
        return freed


@contextlib.contextmanager
def _seed_lease(seed: Path, *, exclusive: bool, blocking: bool = True) -> Iterator[None]:
    """Hold a lease on ``seed``: shared to copy it, exclusive to delete it.

    A `flock` on a sidecar beside the seed (the seed itself is read-only).
    The lock file is never deleted, so every holder locks the same inode; one
    is left per seed ever published, which is a few bytes each.

    Host-local: correct for the API processes on one host that share the
    store's filesystem, and not over NFS.
    """
    lock_path = _sidecar(seed, ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(fd, operation if blocking else operation | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)  # closing the last descriptor releases the flock


def _sidecar(seed: Path, suffix: str) -> Path:
    # Beside the seed, never inside it: the seed's directories are 0o555.
    return seed.parent / f"{seed.name}{suffix}"


def _write_size(seed: Path, size: int) -> None:
    staged = _sidecar(seed, f".size-{uuid.uuid4().hex}")
    staged.write_text(str(size))
    staged.replace(_sidecar(seed, ".size"))


def _recorded_size(seed: Path) -> int:
    """``seed``'s size as `publish` recorded it, or walked when nothing was."""
    try:
        return int(_sidecar(seed, ".size").read_text())
    except (FileNotFoundError, ValueError):
        return _size(seed)


def _copy_writable(source: Path, destination: Path) -> None:
    """Copy ``source`` into ``destination`` as files the workspace may change.

    The container's agent is not the host user that copies, so directories
    are opened to it the same way the provider opens `/workspace` itself, and
    files get read+write: pnpm hardlinks out of its store, and Linux's
    protected_hardlinks refuses that for a file the linker cannot write.
    """
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
    for directory, _dirs, files in os.walk(destination):
        Path(directory).chmod(0o777)
        for name in files:
            path = Path(directory, name)
            if path.is_symlink():
                continue
            mode = path.stat().st_mode
            path.chmod(0o777 if mode & 0o111 else 0o666)


def _make_read_only(root: Path) -> None:
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory, name)
            if not path.is_symlink():
                path.chmod(path.stat().st_mode & 0o555)
        Path(directory).chmod(0o555)


def _remove(root: Path) -> None:
    # A read-only seed's directories must be writable again to be emptied.
    for directory, _dirs, _files in os.walk(root):
        Path(directory).chmod(0o755)
    shutil.rmtree(root)


def _size(root: Path) -> int:
    return sum(
        Path(directory, name).lstat().st_size
        for directory, _dirs, files in os.walk(root)
        for name in files
    )


class SeedableWorkspace(Protocol):
    """What seeding needs of a workspace: its host directory, and a way to run in it."""

    @property
    def path(self) -> Path: ...

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult: ...


async def seed_dependency_caches(
    workspace: SeedableWorkspace, clones: list[tuple[str, Path]]
) -> None:
    """Give a freshly cloned workspace warm caches, warming any seed it lacks.

    MUST run after the clone and before any agent: a missing seed is built
    here, in this workspace, by the platform's own command, and published
    from a cache nothing but that command has written. Once an agent has run,
    the workspace's cache is the agent's and can never become a seed.

    Never raises: a seed only saves work, so one that cannot be copied or
    built leaves the workspace as it was before #1714, installing from cold.
    The file copies run in a thread, not the event loop: a seed is gigabytes.
    """
    store = configured_store()
    if store is None:
        return
    try:
        outcome = await asyncio.to_thread(store.seed, workspace.path, clones)
        for key, clone_dir in outcome.missing:
            await _warm(store, workspace, key, clone_dir)
    except Exception:
        logger.exception("Dependency seeding failed; installing from cold (%s)", workspace.path)
        return
    logger.info(
        "Dependency seeds (workspace=%s, copied=%s, warmed=%s)",
        workspace.path,
        [_label(key) for key in outcome.copied],
        [_label(key) for key, _ in outcome.missing],
    )


async def _warm(
    store: DependencySeedStore, workspace: SeedableWorkspace, key: SeedKey, clone_dir: Path
) -> None:
    scratch = await asyncio.to_thread(_warm_inputs, workspace.path, key.tool, clone_dir)
    in_container = Path("/workspace") / scratch.relative_to(workspace.path)
    try:
        result = await workspace.execute(
            list(WARM_COMMANDS[key.tool]),
            timeout_seconds=_WARM_TIMEOUT_SECONDS,
            working_directory=str(in_container),
            environment={
                **_WARM_ENVIRONMENT,
                "UV_PROJECT_ENVIRONMENT": str(in_container / ".venv"),
            },
        )
    finally:
        # Best effort: the tool may leave files the host user cannot remove,
        # and a leftover scratch directory in a workspace harms nothing.
        await asyncio.to_thread(shutil.rmtree, scratch, True)
    if result.exit_code != 0:
        # Not published: a half-built cache is not a seed. The workspace
        # keeps what it built, so this run is no colder than before.
        logger.warning(
            "Could not warm dependency seed %s (exit %s): %s",
            _label(key),
            result.exit_code,
            (result.stderr or "")[-300:],
        )
        return
    await asyncio.to_thread(store.publish, key, workspace.path / ".cache" / key.tool)


def _warm_inputs(workspace_dir: Path, tool: str, clone_dir: Path) -> Path:
    """A fresh scratch directory holding only what ``tool``'s warm reads of ``clone_dir``.

    Outside the checkout and outside every cache, so nothing the checkout
    ships is there to run. Regular files only, as in `seed_keys`.
    """
    scratch = workspace_dir / f".seed-warm-{uuid.uuid4().hex}"
    scratch.mkdir()
    # Opened to the container's agent user, as `_copy_writable` does: the
    # tool writes its lock state and uv its `.venv` here.
    scratch.chmod(0o777)
    for name in (SEEDED_TOOLS[tool], *WARM_MANIFESTS[tool]):
        path = clone_dir / name
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
        except FileNotFoundError:
            continue
        (scratch / name).write_bytes(path.read_bytes())
    return scratch


def _label(key: SeedKey) -> str:
    return f"{key.tool}:{key.repository}@{key.lockfile_sha256[:12]}"


def configured_store() -> DependencySeedStore | None:
    """The store `SYN_DEPENDENCY_SEED_DIR` names, or None when seeding is off."""
    from syn_shared.settings import get_settings

    settings = get_settings().dependency_seed
    if not settings.dir:
        return None
    return DependencySeedStore(Path(settings.dir), max_bytes=settings.max_bytes)
