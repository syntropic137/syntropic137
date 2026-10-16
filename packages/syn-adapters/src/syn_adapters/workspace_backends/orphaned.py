"""Reaching an orphaned workspace container from startup reconciliation (#1560).

A workspace whose API process died is still a running container at the next
startup, until the reap removes it. That window is the last chance to run the
unpushed-work guard inside it, so this module gives reconciliation exactly what
the guard needs: a `GitWorkspace` over ``docker exec``, the container's own
workspace directory as this process sees it, and a remover for that directory.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from syn_domain.contexts.orchestration import ExecutionResult, OrphanedWorkspace
from syn_shared.env_constants import (
    ENV_SYN_WORKSPACE_CONTAINER_DIR,
    ENV_SYN_WORKSPACE_HOST_DIR,
)

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
    #: Every mount's source, bind or volume, whatever its destination (#1983);
    #: None when the document carries no mount list, which is not "no mounts".
    mount_sources: tuple[str, ...] | None = ()


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


def workspace_host_dir() -> str | None:
    """The workspace base as docker names it on the host, or None when unset."""
    return os.environ.get(ENV_SYN_WORKSPACE_HOST_DIR) or None


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


class _DockerMount(BaseModel):
    """One entry of ``Mounts`` in ``docker inspect``.

    Docker's documents carry many fields this code has no business with, so
    unknown keys are ignored (an external format, not our contract); what is
    read is typed and validated. A mount whose source is missing, or empty
    for anything but a tmpfs, is not "no mount": it rejects the document.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str = Field(default="bind", alias="Type")
    source: str = Field(alias="Source")
    destination: str = Field(alias="Destination")

    @model_validator(mode="after")
    def _source_is_known(self) -> _DockerMount:
        if not self.source and self.type != "tmpfs":
            raise ValueError(f"a {self.type} mount at {self.destination} names no source")
        return self


class _DockerState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    running: bool = Field(default=False, alias="Running")
    paused: bool = Field(default=False, alias="Paused")


class _DockerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    labels: dict[str, str] | None = Field(default=None, alias="Labels")


class _DockerContainer(BaseModel):
    """The parts of one ``docker inspect`` document this module reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    state: _DockerState = Field(default_factory=_DockerState, alias="State")
    config: _DockerConfig = Field(default_factory=_DockerConfig, alias="Config")
    #: Absent is "unknown", never "mounts nothing".
    mounts: tuple[_DockerMount, ...] | None = Field(default=None, alias="Mounts")


_INSPECT = TypeAdapter(list[_DockerContainer])


def parse_inspect(raw: str) -> _Inspected | None:
    """The labels and mounts out of ``docker inspect`` JSON; None when it is not readable.

    Validated as a whole: one malformed mount makes the document unreadable,
    and every caller keeps what it cannot read.
    """
    try:
        documents = _INSPECT.validate_json(raw)
    except ValidationError:
        return None
    if not documents:
        return None
    document = documents[0]
    mounts = document.mounts
    workspace = next(
        (m.source for m in mounts or () if m.destination == _WORKSPACE_MOUNT and m.source), None
    )
    return _Inspected(
        labels=dict(document.config.labels or {}),
        workspace_source=workspace,
        running=document.state.running or document.state.paused,
        mount_sources=None if mounts is None else tuple(m.source for m in mounts if m.source),
    )
