"""Copy operations for AgenticIsolationAdapter.

Extracted from adapter.py to reduce module complexity.
Handles copy_to, copy_from and their helper methods.
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from agentic_isolation import AgenticWorkspace, WorkspaceDockerProvider

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

logger = logging.getLogger(__name__)


def resolve_workspace_path(handle: IsolationHandle) -> Path | None:
    """Validate and return the host workspace path, or None."""
    host_workspace = handle.host_workspace_path
    if not host_workspace:
        logger.warning(
            "copy_from: No host_workspace_path in handle (workspace=%s)",
            handle.isolation_id,
        )
        return None

    workspace_path = Path(host_workspace)
    logger.info(
        "copy_from: Checking path %s (exists=%s, workspace=%s)",
        workspace_path,
        workspace_path.exists(),
        handle.isolation_id,
    )

    if not workspace_path.exists():
        logger.warning(
            "copy_from: Workspace path does not exist (workspace=%s, path=%s)",
            handle.isolation_id,
            workspace_path,
        )
        return None
    return workspace_path


def _normalize_pattern(pattern: str) -> str:
    """Strip leading slashes and 'workspace/' prefix from a glob pattern."""
    clean = pattern.lstrip("/")
    if clean.startswith("workspace/"):
        clean = clean[len("workspace/") :]
    return clean


# Every component is opened relative to the fd of its parent with O_NOFOLLOW,
# so no symlink is followed anywhere on the path, including one swapped in
# after the glob. O_NONBLOCK keeps a FIFO from blocking the open; the fstat
# below rejects anything that is not a regular file.
_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_READ_CHUNK = 1024 * 1024
# Collection-wide bounds, on top of the per-file limit: the total bytes held
# in memory for one collection, and the number of glob matches examined.
MAX_COLLECTION_BYTES = 200 * 1024 * 1024
MAX_COLLECTION_MATCHES = 10_000


class _SkipFileError(Exception):
    """A matched path that is not a regular file inside the workspace."""


def _inside_root(root: Path, file_path: Path) -> bool:
    real = os.path.realpath(file_path)
    return os.path.commonpath([str(root), real]) == str(root)


def _open_contained(root: Path, parts: tuple[str, ...]) -> int:
    """Open root/parts without following a symlink at any component.

    Returns an fd for the final entry; the caller closes it.
    """
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise _SkipFileError("not a plain relative path")
    dir_fd = os.open(root, _DIR_OPEN_FLAGS)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, _DIR_OPEN_FLAGS, dir_fd=dir_fd)
            except OSError as e:
                raise _SkipFileError("a directory on its path is a symlink") from e
            os.close(dir_fd)
            dir_fd = next_fd
        try:
            return os.open(parts[-1], _FILE_OPEN_FLAGS, dir_fd=dir_fd)
        except OSError as e:
            raise _SkipFileError("it is a symlink") from e
    finally:
        os.close(dir_fd)


def _read_bounded(fd: int, max_bytes: int) -> bytes:
    """Read a regular file from fd, refusing more than max_bytes."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise _SkipFileError("not a regular file")
    if st.st_nlink != 1:
        # A second name for the same inode may live outside the workspace.
        raise _SkipFileError(f"it has {st.st_nlink} hard links")
    if st.st_size > max_bytes:
        raise _SkipFileError(f"{st.st_size} bytes exceeds the {max_bytes}-byte limit")
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(fd, min(_READ_CHUNK, max_bytes + 1 - total)):
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            # It grew after the fstat: refuse rather than read on.
            raise _SkipFileError(f"grew past the {max_bytes}-byte limit while being read")
    return b"".join(chunks)


def _try_read_file(
    root: Path,
    file_path: Path,
    relative_path: str,
    max_bytes: int,
    results: list[tuple[str, bytes]],
) -> None:
    """Read one matched file if it is a regular file inside root.

    Workspace contents are written by the agent, so a match is read only when
    it resolves inside the workspace, no component of its path is a symlink,
    it is a regular file with a single hard link, and it is within max_bytes. Anything else is
    skipped with a warning naming the relative path, never its content.
    """
    try:
        if not _inside_root(root, file_path):
            raise _SkipFileError("it resolves outside the workspace")
        fd = _open_contained(root, file_path.relative_to(root).parts)
        try:
            content = _read_bounded(fd, max_bytes)
        finally:
            os.close(fd)
    except _SkipFileError as e:
        logger.warning("copy_from: Skipped %s: %s", relative_path, e)
        return
    except Exception as e:
        logger.warning(
            "copy_from: Failed to read file %s: %s",
            relative_path,
            e,
        )
        return
    results.append((relative_path, content))
    logger.info(
        "copy_from: Collected file %s (%d bytes)",
        relative_path,
        len(content),
    )


def collect_matching_files(
    workspace_path: Path,
    patterns: list[str],
    *,
    max_bytes: int,
    max_total_bytes: int = MAX_COLLECTION_BYTES,
    max_matches: int = MAX_COLLECTION_MATCHES,
) -> list[tuple[str, bytes]]:
    """Glob patterns against workspace and read matching regular files.

    Only regular files inside the workspace are collected: no symlink is
    followed, at the file or at any directory on its path, and a file larger
    than max_bytes is skipped. A file that would take the collection past
    max_total_bytes is skipped, and collection stops after max_matches glob
    matches.
    """
    results: list[tuple[str, bytes]] = []
    seen_paths: set[str] = set()
    root = workspace_path.resolve(strict=True)
    used = 0
    examined = 0

    for pattern in patterns:
        clean_pattern = _normalize_pattern(pattern)

        for file_path in root.glob(clean_pattern):
            examined += 1
            if examined > max_matches:
                logger.warning(
                    "copy_from: Stopped after %d matches; the rest were not collected",
                    max_matches,
                )
                return results
            try:
                if stat.S_ISDIR(file_path.lstat().st_mode):
                    continue
            except OSError:
                continue
            relative_path = str(file_path.relative_to(root))
            if relative_path in seen_paths:
                continue
            seen_paths.add(relative_path)
            limit = min(max_bytes, max_total_bytes - used)
            collected_before = len(results)
            _try_read_file(root, file_path, relative_path, limit, results)
            if len(results) > collected_before:
                used += len(results[-1][1])
    return results


async def copy_to_workspace(
    provider: WorkspaceDockerProvider,
    workspace: object,
    files: list[tuple[str, bytes]],
) -> None:
    """Copy files into workspace via the provider.

    Args:
        provider: The workspace docker provider
        workspace: The workspace object
        files: List of (path, content) tuples
    """
    for path, content in files:
        relative_path = path.lstrip("/")
        await provider.write_file(workspace, relative_path, content)  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary


async def copy_from_workspace(
    handle: IsolationHandle,
    patterns: list[str],
) -> list[tuple[str, bytes]]:
    """Copy files from workspace via mounted volume.

    Runs in a worker thread. The glob, the stats and the reads are blocking
    filesystem calls against a bind mount, and every one of them used to run
    on the API's event loop - the loop that also owns every other execution's
    `docker exec` deadlines. On the selfhost that froze the whole API for
    60-190s at a time, once per phase end (exec-27fed66a653d: 139s). A
    neighbour's setup-phase exec then found its deadline already passed and its
    process already gone, and came back as exit -1 with no output.

    Args:
        handle: Handle from create()
        patterns: Glob patterns to match

    Returns:
        List of (relative_path, content) tuples for matching files
    """
    return await asyncio.to_thread(_copy_from_workspace_blocking, handle, patterns)


def _copy_from_workspace_blocking(
    handle: IsolationHandle,
    patterns: list[str],
) -> list[tuple[str, bytes]]:
    """The blocking half of `copy_from_workspace`. Never call on the event loop.

    There is deliberately no listing of the whole workspace here. One used to
    run "at DEBUG", and DEBUG is always enabled on the logger even when no
    handler prints it (agentic_logging sets the root logger to DEBUG and
    filters at the handler), so it walked every repository, node_modules and
    virtualenv in the workspace - 130-170k entries - to build a message that
    was then thrown away.
    """
    workspace_path = resolve_workspace_path(handle)
    if workspace_path is None:
        return []

    results = collect_matching_files(
        workspace_path,
        patterns,
        max_bytes=get_settings().storage.max_file_size_bytes,
    )

    logger.info(
        "copy_from: Collected %d files matching patterns %s (workspace=%s)",
        len(results),
        patterns,
        handle.isolation_id,
    )
    return results


def check_workspace_health(
    workspaces: dict[str, AgenticWorkspace],
    handle: IsolationHandle,
) -> bool:
    """Check if workspace is healthy (present in active workspaces dict).

    Args:
        workspaces: Active workspaces keyed by isolation_id
        handle: Handle from create()

    Returns:
        True if workspace is running
    """
    return handle.isolation_id in workspaces


async def copy_files_to_workspace(
    workspaces: dict[str, AgenticWorkspace],
    provider: WorkspaceDockerProvider,
    handle: IsolationHandle,
    files: list[tuple[str, bytes]],
    base_path: str = "/workspace",  # noqa: ARG001 - interface param
) -> None:
    """Copy files into workspace.

    Args:
        workspaces: Active workspaces keyed by isolation_id
        provider: The workspace docker provider
        handle: Handle from create()
        files: List of (path, content) tuples
        base_path: Base path (interface param, docker uses mounted volume)
    """
    workspace = workspaces.get(handle.isolation_id)
    if workspace is None:
        raise RuntimeError(f"Workspace not found: {handle.isolation_id}")

    await copy_to_workspace(provider, workspace, files)


async def copy_files_from_workspace(
    handle: IsolationHandle,
    patterns: list[str],
    base_path: str = "/workspace",  # noqa: ARG001 - used for container path mapping
) -> list[tuple[str, bytes]]:
    """Copy files from workspace via mounted volume.

    The Docker provider mounts the workspace directory, so files created
    inside the container are accessible on the host at host_workspace_path.

    Args:
        handle: Handle from create()
        patterns: Glob patterns to match (e.g., ["artifacts/output/**/*"])
        base_path: Base path inside container (not used - we read from host mount)

    Returns:
        List of (relative_path, content) tuples for matching files
    """
    return await copy_from_workspace(handle, patterns)
