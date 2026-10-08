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

- a seed is produced only through `publish`, which the platform calls with a
  cache it built itself. Nothing reads a workspace back into the store;
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
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

#: Each seeded tool, and the lockfile whose hash keys its seed. The cache it
#: seeds is `/workspace/.cache/<tool>`, which is where
#: `agentic.adapter._WORKSPACE_CACHE_ENV` points that tool.
SEEDED_TOOLS: Final[dict[str, str]] = {"uv": "uv.lock", "pnpm": "pnpm-lock.yaml"}

#: A seed copied less than this long ago is never pruned, so a prune cannot
#: delete a seed out from under a copy that is reading it.
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


class DependencySeedStore:
    """Platform-owned seeds on the host, copied into workspaces and pruned LRU."""

    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self._root = root
        self._max_bytes = max_bytes

    def seed(self, workspace_dir: Path, clones: Iterable[tuple[str, Path]]) -> list[SeedKey]:
        """Copy every ready seed for ``clones`` into ``workspace_dir``'s caches.

        ``workspace_dir`` is the host side of `/workspace`; each clone is
        ``(repository, host path of its checkout)``. Returns the seeds copied.
        A missing seed is not an error: that workspace installs from cold.
        """
        copied: list[SeedKey] = []
        for repository, clone_dir in clones:
            for key in seed_keys(repository, clone_dir):
                source = self._root / key.relative_path
                if not source.is_dir():
                    continue
                # Touched BEFORE the copy: it is both the LRU clock and the
                # grace `prune` honours for a seed being read right now.
                os.utime(source)
                _copy_writable(source, workspace_dir / ".cache" / key.tool)
                copied.append(key)
        return copied

    def publish(self, key: SeedKey, built_cache: Path) -> None:
        """Install a cache THE PLATFORM built as the seed for ``key``, then prune.

        Never call this with anything an agent workspace wrote: that is the
        shared writable cache #1310 rejected, one step removed. The cache must
        have been built at the same in-container path a workspace uses
        (`/workspace/.cache/<tool>`): uv's cache holds absolute symlinks.

        ``built_cache`` is moved, not copied, and the move is a rename within
        the store, so a reader sees either no seed or the whole of one.
        """
        target = self._root / key.relative_path
        staging = target.parent / f".staging-{uuid.uuid4().hex}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built_cache, staging, symlinks=True)
        _make_read_only(staging)
        try:
            staging.rename(target)
        except OSError:
            # Another warmer published the same lockfile first; theirs is as good.
            _remove(staging)
        self.prune()

    def prune(self) -> int:
        """Delete least recently copied seeds until the store fits its budget.

        Returns the bytes freed. A seed copied within the grace period is kept
        even over budget: deleting it could truncate a copy in flight.
        """
        seeds = sorted(
            (path.stat().st_mtime, path, _size(path))
            for path in self._root.glob("*/*/*/*")
            if path.is_dir() and not path.name.startswith(".")
        )
        total = sum(size for _, _, size in seeds)
        freed = 0
        cutoff = time.time() - _PRUNE_GRACE_SECONDS
        for mtime, path, size in seeds:
            if total - freed <= self._max_bytes or mtime > cutoff:
                break
            _remove(path)
            freed += size
            logger.info("Pruned dependency seed %s (%d bytes)", path, size)
        return freed


def _copy_writable(source: Path, destination: Path) -> None:
    """Copy ``source`` into ``destination`` as files the workspace may change.

    The container's agent is not the host user that copies, so directories
    are opened to it the same way the provider opens `/workspace` itself, and
    files get read+write: pnpm hardlinks out of its store, and Linux's
    protected_hardlinks refuses that for a file the linker cannot write.
    """
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
    for directory, _dirs, files in os.walk(destination):
        os.chmod(directory, 0o777)
        for name in files:
            path = Path(directory, name)
            if path.is_symlink():
                continue
            mode = path.stat().st_mode
            os.chmod(path, 0o777 if mode & 0o111 else 0o666)


def _make_read_only(root: Path) -> None:
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory, name)
            if not path.is_symlink():
                os.chmod(path, path.stat().st_mode & 0o555)
        os.chmod(directory, 0o555)


def _remove(root: Path) -> None:
    # A read-only seed's directories must be writable again to be emptied.
    for directory, _dirs, _files in os.walk(root):
        os.chmod(directory, 0o755)
    shutil.rmtree(root)


def _size(root: Path) -> int:
    return sum(
        Path(directory, name).lstat().st_size
        for directory, _dirs, files in os.walk(root)
        for name in files
    )


async def seed_dependency_caches(workspace_dir: Path, clones: list[tuple[str, Path]]) -> None:
    """Seed a freshly cloned workspace's caches, if seeding is configured.

    Never raises: a seed only saves work, so a seed that cannot be copied
    leaves the workspace exactly as it was before #1714, installing from cold.
    The copy is a thread, not the event loop: a seed is gigabytes.
    """
    store = configured_store()
    if store is None:
        return
    try:
        copied = await asyncio.to_thread(store.seed, workspace_dir, clones)
    except Exception:
        logger.exception("Dependency seeding failed; installing from cold (%s)", workspace_dir)
        return
    logger.info(
        "Dependency seeds copied (workspace=%s, seeds=%s)",
        workspace_dir,
        [f"{key.tool}:{key.repository}@{key.lockfile_sha256[:12]}" for key in copied],
    )


def configured_store() -> DependencySeedStore | None:
    """The store `SYN_DEPENDENCY_SEED_DIR` names, or None when seeding is off."""
    from syn_shared.settings import get_settings

    settings = get_settings().dependency_seed
    if not settings.dir:
        return None
    return DependencySeedStore(Path(settings.dir), max_bytes=settings.max_bytes)
