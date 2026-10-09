"""Reaching an orphaned workspace container from startup reconciliation (#1560).

A workspace whose API process died is still a running container at the next
startup, until the reap removes it. That window is the last chance to run the
unpushed-work guard inside it, so this module gives reconciliation exactly what
the guard needs: a `GitWorkspace` over ``docker exec``, the container's own
workspace directory as this process sees it, and a remover for that directory.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from syn_domain.contexts.orchestration import ExecutionResult, OrphanedWorkspace
from syn_shared.env_constants import ENV_SYN_WORKSPACE_CONTAINER_DIR

#: Mount point of the workspace directory inside every workspace container.
_WORKSPACE_MOUNT = "/workspace"


class DockerExecWorkspace:
    """`GitWorkspace` over ``docker exec`` into a container this process did not start."""

    def __init__(self, container_id: str) -> None:
        self._container_id = container_id

    async def execute(self, command: list[str]) -> ExecutionResult:
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            self._container_id,
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        exit_code = proc.returncode if proc.returncode is not None else -1
        return ExecutionResult(
            exit_code=exit_code,
            success=exit_code == 0,
            duration_ms=(time.monotonic() - started) * 1000,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    async def renew_git_credential(self) -> object:
        """Nothing to renew from: the process that held this workspace's
        credential source is the one that died. The guard then pushes with
        whatever the container still holds and reports the result honestly,
        and a refused push keeps the directory."""
        return ()


@dataclass(frozen=True)
class _Inspected:
    labels: dict[str, str]
    workspace_source: str | None
    running: bool = False


async def find_orphaned_workspaces(container_ids: list[str]) -> list[OrphanedWorkspace]:
    """The Syntropic137 workspaces among ``container_ids``, ready to be guarded.

    Containers without an execution label or a ``/workspace`` mount are not
    ours to judge and are skipped; so is any whose ``docker inspect`` fails.
    """
    orphans: list[OrphanedWorkspace] = []
    for container_id in container_ids:
        inspected = await _inspect(container_id)
        if inspected is None or inspected.workspace_source is None:
            continue
        execution_id = inspected.labels.get("syn.execution_id")
        if not execution_id:
            continue
        workspace_id = Path(inspected.workspace_source).name
        orphans.append(
            OrphanedWorkspace(
                workspace=DockerExecWorkspace(container_id),
                workspace_id=workspace_id,
                execution_id=execution_id,
                host_dir=_local_path(workspace_id),
            )
        )
    return orphans


class ShutilWorkspaceDirRemover:
    """`WorkspaceDirRemover` over ``shutil.rmtree``. Raises ``OSError`` on failure."""

    def remove(self, host_dir: str) -> None:
        shutil.rmtree(host_dir)


def workspace_base_dir() -> str:
    """The workspace base directory as this process sees it."""
    return os.environ.get(ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces")


def _local_path(workspace_id: str) -> str:
    """Where this process sees the directory docker mounted from the host.

    The provider names every workspace directory after its workspace id under
    one base (SYN_WORKSPACE_HOST_DIR on the host, SYN_WORKSPACE_CONTAINER_DIR
    here), so the basename of the mount source is the same on both sides.
    """
    return str(Path(workspace_base_dir()) / workspace_id)


async def _inspect(container_id: str) -> _Inspected | None:
    raw = await docker_inspect_raw(container_id)
    return None if raw is None else parse_inspect(raw)


async def docker_inspect_raw(container_id: str) -> str | None:
    """``docker inspect`` output for one container, or None if it could not be read."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode(errors="replace")


def parse_inspect(raw: str) -> _Inspected | None:
    """The labels and the ``/workspace`` mount source out of ``docker inspect`` JSON."""
    try:
        documents: object = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(documents, list) or not documents or not isinstance(documents[0], dict):
        return None
    document: dict[object, object] = documents[0]
    state = document.get("State")
    running = isinstance(state, dict) and state.get("Running") is True
    return _Inspected(
        labels=_labels(document), workspace_source=_workspace_source(document), running=running
    )


def _labels(document: dict[object, object]) -> dict[str, str]:
    config = document.get("Config")
    raw = config.get("Labels") if isinstance(config, dict) else None
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _workspace_source(document: dict[object, object]) -> str | None:
    mounts = document.get("Mounts")
    if not isinstance(mounts, list):
        return None
    for mount in mounts:
        if isinstance(mount, dict) and mount.get("Destination") == _WORKSPACE_MOUNT:
            return str(mount.get("Source") or "") or None
    return None
