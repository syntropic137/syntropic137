"""Copy operations for AgenticIsolationAdapter.

Extracted from adapter.py to reduce module complexity.
Handles copy_to, copy_from and their helper methods.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

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


def _try_read_file(
    file_path: Path,
    relative_path: str,
    results: list[tuple[str, bytes]],
) -> None:
    """Read a single file, appending to results on success."""
    try:
        content = file_path.read_bytes()
        results.append((relative_path, content))
        logger.info(
            "copy_from: Collected file %s (%d bytes)",
            relative_path,
            len(content),
        )
    except Exception as e:
        logger.warning(
            "copy_from: Failed to read file %s: %s",
            relative_path,
            e,
        )


def collect_matching_files(
    workspace_path: Path,
    patterns: list[str],
) -> list[tuple[str, bytes]]:
    """Glob patterns against workspace and read matching files."""
    results: list[tuple[str, bytes]] = []
    seen_paths: set[str] = set()

    for pattern in patterns:
        clean_pattern = _normalize_pattern(pattern)

        for file_path in workspace_path.glob(clean_pattern):
            if not file_path.is_file():
                continue
            relative_path = str(file_path.relative_to(workspace_path))
            if relative_path in seen_paths:
                continue
            seen_paths.add(relative_path)
            _try_read_file(file_path, relative_path, results)
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

    results = collect_matching_files(workspace_path, patterns)

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
