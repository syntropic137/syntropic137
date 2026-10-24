"""Whether a workspace started with its session-store capability degraded (#1516).

Since agentic-workspace #27 an unreachable session store no longer fails the
workspace. The entrypoint starts it with capture DISABLED and records the
verdict as a `capability_status` audit row. `AGENTIC_SESSION_STORE_READY=0` is
not a usable signal: agents run through `docker exec`, so that env reaches the
container's own command and nothing else. The audit row is the channel.

WHERE THE FORMAT LIVES. The row's location, shape and host filter belong to
agentic-workspace and are read by its `read_capability_status`; nothing here
parses the audit file. What syn137 keeps is what the verdict MEANS for an
execution, expressed as `CapabilityVerdict`, behind `CapabilityStatusReader`
so the capture service depends on a port rather than on the module.

FAIL-OPEN. Capture is telemetry. A verdict that cannot be read is UNKNOWN,
returned as None exactly like "no row", and never fails the run that asked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final, Literal, Protocol

from agentic_isolation.capability_status import CapabilityStatusError, read_capability_status
from agentic_isolation.providers.base import ExecuteResult
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agentic_isolation.harnesses import ExecFn

    from syn_adapters.workspace_backends.agentic.capture_observation import (
        ObservationWriter,
    )
    from syn_adapters.workspace_backends.agentic.capture_probe import WorkspaceExecutor
    from syn_shared.events import EventType

__all__ = [
    "CAPABILITY_STATUS_OBSERVATION",
    "SESSION_STORE_CAPABILITY",
    "AgenticCapabilityStatusReader",
    "CapabilityStatusReader",
    "CapabilityStatusValue",
    "CapabilityVerdict",
    "record_capability_verdict",
]

logger = logging.getLogger(__name__)

#: The capability name agentic-workspace gives the session store.
SESSION_STORE_CAPABILITY: Final = "session-store"

#: The Lane 2 row a start-up verdict is recorded as, spelled by syn_shared for
#: the reason `SESSION_CAPTURE_OBSERVATION` is: that spelling gates the write.
CAPABILITY_STATUS_OBSERVATION: Final[EventType] = "capability_status"

#: The same bounded slice of the run a capture verdict's write gets.
_WRITE_TIMEOUT_SECONDS: Final = 5.0

#: Used when the reader passes no timeout of its own.
_DEFAULT_TIMEOUT_SECONDS: Final = 10


#: The verdicts agentic-workspace's capability status contract defines.
CapabilityStatusValue = Literal["ready", "degraded", "failed"]


class CapabilityVerdict(BaseModel):
    """How one capability came up in one workspace, as syn137 records it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    status: CapabilityStatusValue
    failed_checks: tuple[str, ...] = ()
    doctor_exit: int = 0

    @property
    def degraded(self) -> bool:
        """True when the workspace ran with this capability switched off."""
        return self.status == "degraded"


class CapabilityStatusReader(Protocol):
    """Reads a capability's start-up verdict from a still-running workspace."""

    async def read(self, execute: WorkspaceExecutor, capability: str) -> CapabilityVerdict | None:
        """The verdict, or None when it is unknown: no row, or no readable one."""
        ...


class AgenticCapabilityStatusReader:
    """`CapabilityStatusReader` over agentic-workspace's typed reader."""

    async def read(self, execute: WorkspaceExecutor, capability: str) -> CapabilityVerdict | None:
        try:
            status = await read_capability_status(_exec_fn_for(execute), capability)
        except CapabilityStatusError as exc:
            # Unknown, not degraded and not a failure: guessing either way
            # would misreport a workspace whose capture may well be working.
            logger.warning("could not read %s capability status: %s", capability, exc)
            return None
        except Exception:
            # An exec that broke (timeout, a container gone mid-read) is the
            # same unknown. Exception, not BaseException: cancellation must
            # keep propagating, or a shutdown hangs on a telemetry read.
            logger.exception("reading %s capability status failed", capability)
            return None
        if status is None:
            return None
        return CapabilityVerdict(
            capability=status.capability,
            status=status.status.value,
            failed_checks=status.failed_checks,
            doctor_exit=status.doctor_exit,
        )


async def record_capability_verdict(
    writer: ObservationWriter | None,
    verdict: CapabilityVerdict,
    *,
    session_id: str,
    execution_id: str,
    phase_id: str,
    workspace_id: str,
) -> None:
    """Record a start-up verdict on Lane 2, as its own row.

    Its own row, not a field of the teardown capture verdict: it is a fact
    about the START, so it is written while the agent is still running and
    survives a phase that never reaches teardown (#1516). Best-effort like
    every observation: a failed write is logged and dropped.
    """
    if writer is None:
        return
    try:
        await asyncio.wait_for(
            writer.record_observation(
                session_id=session_id,
                observation_type=CAPABILITY_STATUS_OBSERVATION,
                data=verdict.model_dump(mode="json"),
                execution_id=execution_id,
                phase_id=phase_id,
                workspace_id=workspace_id,
            ),
            timeout=_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("could not record %s capability status: %s", verdict.capability, exc)


def _exec_fn_for(execute: WorkspaceExecutor) -> ExecFn:
    """Adapt the argv executor to the shell-string `ExecFn` the reader takes.

    The string arrives as `sh -c`'s operand, or the quoting `exec_argv` applied
    would be quoted a second time into literals.
    """

    async def exec_fn(
        command: str,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecuteResult:
        del cwd  # the read script uses absolute paths only
        result = await execute(
            ["sh", "-c", command],
            timeout_seconds=int(timeout) if timeout else _DEFAULT_TIMEOUT_SECONDS,
            environment=env,
        )
        return ExecuteResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
        )

    return exec_fn
