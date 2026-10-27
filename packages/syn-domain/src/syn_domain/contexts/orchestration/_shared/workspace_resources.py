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
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: The smallest memory a workspace may be given, in MB. The same floor
#: ``SYN_WORKSPACE_MEMORY_LIMIT_MB`` has: below it an agent CLI cannot start.
MIN_WORKSPACE_MEMORY_MB = 256


class WorkspaceResourceRequest(BaseModel):
    """What one phase's workspace asks for beyond the deployment default.

    Every field is optional and None means "the deployment default". It is
    a REQUEST: the deployment decides whether it fits (``require_memory_within_cap``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_mb: int | None = Field(default=None, ge=MIN_WORKSPACE_MEMORY_MB)
    """Memory for this phase's workspace container, in MB. None: the default."""

    def memory_mb_or(self, default_mb: int) -> int:
        """The memory this phase's workspace gets, given the deployment default."""
        return default_mb if self.memory_mb is None else self.memory_mb


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


def stored_resource_request(stored: object) -> WorkspaceResourceRequest:
    """A phase's request as an event or projection stored it; the default when absent."""
    if stored is None:
        return WorkspaceResourceRequest()
    return WorkspaceResourceRequest.model_validate(stored)
