"""A phase's workspace resource request, and the deployment cap it must fit (okrs-51p.30).

Workspace memory used to be deployment-wide: ``SYN_WORKSPACE_MEMORY_LIMIT_MB``
sized EVERY workspace. A build that needs 12 GB could only get it by raising
every workspace to 12 GB, which spends the host on runs that never use it and
cuts how many run at once (docs/north-star.md).

So a phase may declare what its workspace needs:

    phases:
      - id: build
        resources:
          memory_mb: 12288

A phase that declares nothing gets the deployment default, exactly as before.
A request is bounded by the deployment's ceiling (``SYN_WORKSPACE_MEMORY_MAX_MB``)
and a request above it is REFUSED, never clamped: a build given less memory
than it declared fails late and looks like a code bug (exit 137), which is
the worst place to learn the deployment cannot run it.

Workspaces are per phase (one container per phase, torn down at its end), so
the request is per phase too: a workflow whose build phase needs 12 GB does
not hold 12 GB through its review phases.

The process limit works the same way (``resources.pids_limit``). Every
workspace runs under ``SYN_WORKSPACE_PIDS_LIMIT`` processes and threads (256
by default), and a test suite that spawns workers and threads per core
(cargo, libtest, ``node --test``, lavapipe) exceeds it. A phase may ask for
more, bounded by ``SYN_WORKSPACE_PIDS_MAX``, and is refused above it: a build
given fewer pids than it needs fails late with EAGAIN ("Resource
temporarily unavailable"), which reads like a code bug. Unlike memory, pids
are not a pooled host budget, so a larger request is not counted against
concurrent admission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from syn_shared.settings.workspace import MIN_WORKSPACE_PIDS_LIMIT as _SETTINGS_PIDS_FLOOR

if TYPE_CHECKING:
    from collections.abc import Iterable

#: The smallest memory a workspace may be given, in MB. The same floor
#: ``SYN_WORKSPACE_MEMORY_LIMIT_MB`` has: below it an agent CLI cannot start.
MIN_WORKSPACE_MEMORY_MB = 256

#: The smallest process limit a workspace may be given: the floor
#: ``SYN_WORKSPACE_PIDS_LIMIT`` has (64), imported so the two cannot drift.
#: Below it an agent CLI and its shell tools cannot start.
MIN_WORKSPACE_PIDS_LIMIT: Final = _SETTINGS_PIDS_FLOOR


class WorkspaceResourceRequest(BaseModel):
    """What one phase's workspace asks for beyond the deployment default.

    Every field is optional and None means "the deployment default". It is
    a REQUEST: the deployment decides whether it fits (``require_memory_within_cap``,
    ``require_pids_within_cap``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_mb: int | None = Field(default=None, ge=MIN_WORKSPACE_MEMORY_MB)
    """Memory for this phase's workspace container, in MB. None: the default."""

    def memory_mb_or(self, default_mb: int) -> int:
        """The memory this phase's workspace gets, given the deployment default."""
        return default_mb if self.memory_mb is None else self.memory_mb

    pids_limit: int | None = Field(default=None, ge=MIN_WORKSPACE_PIDS_LIMIT)
    """Processes and threads this phase's workspace container may hold
    (``--pids-limit``). None: the default."""

    def pids_limit_or(self, default: int) -> int:
        """The pids limit this phase's workspace gets, given the deployment default."""
        return default if self.pids_limit is None else self.pids_limit


class WorkspaceMemoryOverCapError(ValueError):
    """A phase asked for more workspace memory than this deployment allows."""

    def __init__(self, *, requested_mb: int, cap_mb: int, phase_id: str | None) -> None:
        where = f"Phase '{phase_id}'" if phase_id else "A phase"
        super().__init__(
            f"{where} requests resources.memory_mb={requested_mb}, above this "
            f"deployment's workspace memory ceiling of {cap_mb} MB "
            "(SYN_WORKSPACE_MEMORY_MAX_MB). Lower the request, or have the "
            "operator raise the ceiling. Refused rather than clamped: a "
            "workspace given less memory than it declared is OOM-killed mid-run."
        )
        self.requested_mb = requested_mb
        self.cap_mb = cap_mb
        self.phase_id = phase_id


class WorkspacePidsOverCapError(ValueError):
    """A phase asked for a higher workspace pids limit than this deployment allows."""

    def __init__(self, *, requested: int, cap: int, phase_id: str | None) -> None:
        where = f"Phase '{phase_id}'" if phase_id else "A phase"
        super().__init__(
            f"{where} requests resources.pids_limit={requested}, above this "
            f"deployment's workspace pids ceiling of {cap} "
            "(SYN_WORKSPACE_PIDS_MAX). Lower the request, or have the operator "
            "raise the ceiling. Refused rather than clamped: a workspace given "
            "fewer pids than it declared fails late with EAGAIN "
            "('Resource temporarily unavailable'), which reads like a code bug."
        )
        self.requested = requested
        self.cap = cap
        self.phase_id = phase_id


def require_memory_within_cap(
    request: WorkspaceResourceRequest, cap_mb: int, *, phase_id: str | None
) -> None:
    """Raise ``WorkspaceMemoryOverCapError`` when ``request`` asks for more than ``cap_mb``.

    A request at or below the cap, or none at all, passes.
    """
    if request.memory_mb is not None and request.memory_mb > cap_mb:
        raise WorkspaceMemoryOverCapError(
            requested_mb=request.memory_mb, cap_mb=cap_mb, phase_id=phase_id
        )


def deployment_memory_ceiling_mb() -> int:
    """The most workspace memory a phase may request on this deployment.

    ``SYN_WORKSPACE_MEMORY_MAX_MB``, or the default limit when it is unset.
    Read by every check above provisioning: install, start and resume.
    """
    from syn_shared.settings import get_settings

    return get_settings().workspace.memory_ceiling_mb


def require_pids_within_cap(
    request: WorkspaceResourceRequest, cap: int, *, phase_id: str | None
) -> None:
    """Raise ``WorkspacePidsOverCapError`` when ``request`` asks for more pids than ``cap``.

    A request at or below the cap, or none at all, passes.
    """
    if request.pids_limit is not None and request.pids_limit > cap:
        raise WorkspacePidsOverCapError(requested=request.pids_limit, cap=cap, phase_id=phase_id)


def deployment_pids_ceiling() -> int:
    """The highest workspace pids limit a phase may request on this deployment.

    ``SYN_WORKSPACE_PIDS_MAX``, or the default limit when it is unset. Read by
    every check above provisioning: install, start and resume.
    """
    from syn_shared.settings import get_settings

    return get_settings().workspace.pids_ceiling


def require_within_caps(
    request: WorkspaceResourceRequest,
    *,
    memory_cap_mb: int,
    pids_cap: int,
    phase_id: str | None,
) -> None:
    """Hold one phase's request to every ceiling: memory, then pids."""
    require_memory_within_cap(request, memory_cap_mb, phase_id=phase_id)
    require_pids_within_cap(request, pids_cap, phase_id=phase_id)


def require_phases_within_cap(
    phases: Iterable[object], cap_mb: int | None = None, *, pids_cap: int | None = None
) -> None:
    """Refuse the first phase whose request exceeds a ceiling (the deployment's when None).

    ``cap_mb`` bounds ``resources.memory_mb``; ``pids_cap`` bounds
    ``resources.pids_limit``. Takes anything with ``phase_id`` and
    ``resources``: a template's ``PhaseDefinition`` or a run's pinned
    ``ExecutablePhase``. A phase with no ``resources`` (stored before the field
    existed) requests nothing.
    """
    memory_ceiling = deployment_memory_ceiling_mb() if cap_mb is None else cap_mb
    pids_ceiling = deployment_pids_ceiling() if pids_cap is None else pids_cap
    for phase in phases:
        resources = getattr(phase, "resources", None)
        if isinstance(resources, WorkspaceResourceRequest):
            require_within_caps(
                resources,
                memory_cap_mb=memory_ceiling,
                pids_cap=pids_ceiling,
                phase_id=getattr(phase, "phase_id", None),
            )


def stored_resource_request(stored: object) -> WorkspaceResourceRequest:
    """A phase's request as an event or projection stored it; the default when absent."""
    if stored is None:
        return WorkspaceResourceRequest()
    return WorkspaceResourceRequest.model_validate(stored)
