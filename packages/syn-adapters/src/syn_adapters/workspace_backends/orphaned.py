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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    ValidationError,
    model_validator,
)

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
    #: The container's name without docker's leading slash; "" when unnamed.
    name: str = ""
    #: Why this container could NOT be a pure observer of the host tree, or
    #: None when every observer condition holds (`observer_unsafe`).
    observer_unsafe: str | None = "not inspected"


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
    #: ``RW`` exactly as docker reports it. Strict: ``"false"`` or ``0`` is
    #: not a boolean and rejects the document; absent is None, never read-only.
    rw: StrictBool | None = Field(default=None, alias="RW")
    #: Bind propagation (``rprivate``, ``rslave``...); "" or absent for volumes.
    propagation: str | None = Field(default=None, alias="Propagation")

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


class _BindOptions(BaseModel):
    """``HostConfig.Mounts[].BindOptions``: only ``--mount`` binds carry it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    #: ``bind-recursive=readonly``: every submount read-only too, or the
    #: container fails to start. A plain ``ro`` bind falls back to writable
    #: submounts where the kernel cannot do recursive read-only, and inspect
    #: does not show the fallback; this flag is the only proof.
    read_only_force_recursive: StrictBool | None = Field(
        default=None, alias="ReadOnlyForceRecursive"
    )


class _HostMount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    target: str = Field(default="", alias="Target")
    bind_options: _BindOptions | None = Field(default=None, alias="BindOptions")


class _HostConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    privileged: StrictBool | None = Field(default=None, alias="Privileged")
    cap_add: tuple[str, ...] | None = Field(default=None, alias="CapAdd")
    mounts: tuple[_HostMount, ...] | None = Field(default=None, alias="Mounts")


class _DockerContainer(BaseModel):
    """The parts of one ``docker inspect`` document this module reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    host_config: _HostConfig | None = Field(default=None, alias="HostConfig")
    name: str = Field(default="", alias="Name")
    state: _DockerState = Field(default_factory=_DockerState, alias="State")
    config: _DockerConfig = Field(default_factory=_DockerConfig, alias="Config")
    #: Absent is "unknown", never "mounts nothing".
    mounts: tuple[_DockerMount, ...] | None = Field(default=None, alias="Mounts")


_INSPECT = TypeAdapter(list[_DockerContainer])

#: The one propagation mode accepted: ``rprivate`` isolates the bind and every
#: existing descendant mount from later host mount events. ``private`` does
#: not reach existing descendants, and ``rslave``/``rshared`` import new host
#: mounts. Docker's documented default for binds is ``rprivate`` ("Bind
#: propagation defaults to rprivate",
#: https://docs.docker.com/engine/storage/bind-mounts/#configure-bind-propagation),
#: and Engine 29.8.0 reports it explicitly, so an absent value is that default.
_ISOLATED_PROPAGATION = "rprivate"

#: Capabilities that let a container remount what it was given read-only.
_REMOUNT_CAPS = frozenset({"SYS_ADMIN", "CAP_SYS_ADMIN", "ALL"})


def observer_unsafe(document: _DockerContainer) -> str | None:
    """Why the container could write through, or later see, the host tree; None when it cannot.

    The conditions an operator-listed observer (``SYN_DISK_RECLAIM_OBSERVER_CONTAINERS``)
    must meet, from the container's own inspect, on every pass:

    * every mount, each record on its own, is ``RW: false`` (a strict boolean);
    * not privileged, and no capability that can remount (``SYS_ADMIN``);
    * every bind's propagation is ``rprivate``, explicitly or as the default;
    * every bind is FORCED recursively read-only: a ``--mount`` with
      ``bind-recursive=readonly``, which inspect reports as
      ``BindOptions.ReadOnlyForceRecursive: true``. A ``-v`` bind cannot say it.
    """
    host = document.host_config
    if document.mounts is None:
        return "its mounts are unknown"
    if host is None:
        return "its HostConfig is unknown"
    forced = {
        m.target
        for m in host.mounts or ()
        if m.bind_options is not None and m.bind_options.read_only_force_recursive is True
    }
    return _host_unsafe(host) or next(
        filter(None, (_mount_unsafe(m, forced) for m in document.mounts)), None
    )


def _host_unsafe(host: _HostConfig) -> str | None:
    if host.privileged is not False:
        return "it is privileged or may be"
    if any(cap.upper() in _REMOUNT_CAPS for cap in host.cap_add or ()):
        return "it adds a capability that can remount (SYS_ADMIN)"
    return None


def _mount_unsafe(mount: _DockerMount, forced: set[str]) -> str | None:
    """One mount record on its own: a writable duplicate is not hidden by a read-only one."""
    if mount.rw is not False:
        return f"its mount at {mount.destination} is not read-only (RW {mount.rw})"
    if mount.type != "bind":
        return None
    if (mount.propagation or _ISOLATED_PROPAGATION) != _ISOLATED_PROPAGATION:
        return f"its bind at {mount.destination} has {mount.propagation} propagation, not rprivate"
    if mount.destination not in forced:
        return (
            f"its bind at {mount.destination} is not forced recursively read-only "
            "(--mount ...,bind-recursive=readonly)"
        )
    return None


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
        name=document.name.removeprefix("/"),
        observer_unsafe=observer_unsafe(document),
    )
