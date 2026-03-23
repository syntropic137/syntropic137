"""Copy operations for AgenticIsolationAdapter.

Extracted from adapter.py to reduce module complexity.
Handles copy_to, copy_from and their helper methods.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_isolation import WorkspaceDockerProvider

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
        workspace_path, workspace_path.exists(), handle.isolation_id,
    )

    if not workspace_path.exists():
        logger.warning(
            "copy_from: Workspace path does not exist (workspace=%s, path=%s)",
            handle.isolation_id, workspace_path,
        )
        return None
    return workspace_path


def log_workspace_contents(workspace_path: Path) -> None:
    """Log workspace directory contents at DEBUG level."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    try:
        all_files = list(workspace_path.rglob("*"))
        logger.debug(
            "copy_from: Found %d total files in workspace: %s",
            len(all_files),
            [str(f.relative_to(workspace_path)) for f in all_files[:20]],
        )
    except Exception as e:
        logger.debug("copy_from: Failed to list files: %s", e)


def collect_matching_files(
    workspace_path: Path, patterns: list[str],
) -> list[tuple[str, bytes]]:
    """Glob patterns against workspace and read matching files."""
    results: list[tuple[str, bytes]] = []
    seen_paths: set[str] = set()

    for pattern in patterns:
        clean_pattern = pattern.lstrip("/")
        if clean_pattern.startswith("workspace/"):
            clean_pattern = clean_pattern[len("workspace/"):]

        for file_path in workspace_path.glob(clean_pattern):
            if not file_path.is_file():
                continue
            relative_path = str(file_path.relative_to(workspace_path))
            if relative_path in seen_paths:
                continue
            seen_paths.add(relative_path)
            try:
                content = file_path.read_bytes()
                results.append((relative_path, content))
                logger.info(
                    "copy_from: Collected file %s (%d bytes)",
                    relative_path, len(content),
                )
            except Exception as e:
                logger.warning(
                    "copy_from: Failed to read file %s: %s",
                    relative_path, e,
                )
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

    Args:
        handle: Handle from create()
        patterns: Glob patterns to match

    Returns:
        List of (relative_path, content) tuples for matching files
    """
    workspace_path = resolve_workspace_path(handle)
    if workspace_path is None:
        return []

    log_workspace_contents(workspace_path)
    results = collect_matching_files(workspace_path, patterns)

    logger.info(
        "copy_from: Collected %d files matching patterns %s (workspace=%s)",
        len(results), patterns, handle.isolation_id,
    )
    return results
