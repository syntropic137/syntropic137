"""What the workspace decided about the session store before the agent ran (#1516).

Since agentic-workspace #27 an unreachable session store no longer fails the
workspace. The entrypoint runs the capability's doctor, and on a failure with a
``degrade`` policy it starts the workspace with capture DISABLED and appends a
``capability_status`` audit row saying so. Without reading that row, a degraded
run is indistinguishable from a captured one until someone notices transcripts
missing from the store.

THE ROW IS THE ONLY CHANNEL. ``AGENTIC_SESSION_STORE_READY=0`` is exported to
the container's own command only; agents and the host reach the container
through ``docker exec`` and never see it.

THE FORMAT IS NOT OURS. agentic-workspace owns the row and its reader
(``agentic_isolation.capability_status``), so this module never parses the
audit file: it calls that reader and translates the answer into
``StartCapability``, the one shape syn137 depends on. The consumer depends on
``CapabilityStatusReader``, never on the module, so a harness-side change lands
in the submodule and nowhere here.

FAIL-OPEN. A status that cannot be read is "unknown" (``None``), never a run
failure, matching the capture policy it reports on. Cancellation propagates.
"""

from __future__ import annotations

import logging
import math
import shlex
from typing import TYPE_CHECKING, Final, Literal, Protocol

from agentic_isolation.capability_status import (
    CapabilityState,
    CapabilityStatusError,
    read_capability_status,
)
from agentic_isolation.providers.base import ExecuteResult
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.capture_probe import WorkspaceExecutor

__all__ = [
    "SESSION_STORE_CAPABILITY",
    "AgenticCapabilityStatusReader",
    "CapabilityStatusReader",
    "StartCapability",
]

logger = logging.getLogger(__name__)

SESSION_STORE_CAPABILITY: Final = "session-store"

#: Bounded like the capture probe: a hung read must not extend teardown.
_READ_TIMEOUT_SECONDS: Final = 10

StartStatus = Literal["ready", "degraded", "failed"]

_START_STATUS: Final[dict[CapabilityState, StartStatus]] = {
    CapabilityState.READY: "ready",
    CapabilityState.DEGRADED: "degraded",
    CapabilityState.FAILED: "failed",
}


class StartCapability(BaseModel):
    """The lifecycle's verdict on one capability, as syn137 records it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    status: StartStatus
    failed_checks: tuple[str, ...] = ()
    doctor_exit: int = 0

    @property
    def degraded(self) -> bool:
        """True when the workspace ran with this capability disabled."""
        return self.status == "degraded"


class CapabilityStatusReader(Protocol):
    """Reads a capability's start verdict from a still-running workspace.

    ``None`` means unknown: no row (the capability was not active) or a read
    that failed. Implementations never raise for either.
    """

    async def read(
        self, execute: WorkspaceExecutor, capability: str
    ) -> StartCapability | None: ...


class AgenticCapabilityStatusReader:
    """``CapabilityStatusReader`` over agentic-workspace's typed reader."""

    async def read(self, execute: WorkspaceExecutor, capability: str) -> StartCapability | None:
        async def exec_fn(
            command: str,
            *,
            timeout: float | None = None,
            cwd: str | None = None,
            env: dict[str, str] | None = None,
        ) -> ExecuteResult:
            # The AW reader shell-quotes its argv with shlex.join; splitting
            # it back recovers the exact argv for our argv-based executor.
            del cwd  # the read script uses absolute paths only
            seconds = math.ceil(timeout) if timeout is not None else _READ_TIMEOUT_SECONDS
            result = await execute(shlex.split(command), timeout_seconds=seconds, environment=env)
            return ExecuteResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=result.timed_out,
            )

        try:
            row = await read_capability_status(
                exec_fn, capability, timeout=float(_READ_TIMEOUT_SECONDS)
            )
        except CapabilityStatusError as exc:
            logger.warning("could not read %s capability status: %s", capability, exc)
            return None
        except Exception as exc:  # fail-open: an unreadable verdict is unknown
            logger.warning("reading %s capability status failed: %s", capability, exc)
            return None
        if row is None:
            return None
        return StartCapability(
            capability=row.capability,
            status=_START_STATUS[row.status],
            failed_checks=row.failed_checks,
            doctor_exit=row.doctor_exit,
        )
