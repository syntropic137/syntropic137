"""Ask the exporter, from the host, whether this workspace's sessions landed.

THE POINT IS WHO ASKS. The finalizer inside the container also reports a
verdict, and `capture_status` can read it, but the agent runs as the same Unix
user as the finalizer and can print anything it can. This module runs the
exporter as a distinct command issued BY THE HOST and reads its exit status and
JSON, which is a channel the agent has no handle on.

TIMING IS NOT NEGOTIABLE. The probe must run while the container is still
RUNNING: once it is stopped there is nothing to exec into, and once it is
removed the spool is gone with it. That is why this belongs at the
`while_running` point of a staged teardown rather than anywhere convenient.

FAILING TO ASK IS NOT A FAILURE OF THE RUN. Capture is fail-open by policy: a
transcript that did not reach the store must never turn an hour of successful
agent work into a failed phase. So nothing here raises. Every path returns a
verdict, and the ones that mean "we could not find out" return states whose
`needs_backfill` is true, so a later pass re-sends rather than assuming the
best.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

from syn_adapters.workspace_backends.agentic.capture_result import (
    AuthoritativeCapture,
    CaptureExpectations,
    parse_capture_result,
)
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState

__all__ = ["EXPORTER_PROBE_COMMAND", "WorkspaceExecutor", "probe_capture"]

logger = logging.getLogger(__name__)

#: The standard-anchored binary name, matching what agentic-primitives resolves
#: first. `--json` is the supported machine interface; the prose line the
#: finalizer prints is explicitly not a contract.
EXPORTER_PROBE_COMMAND: Final = ["apss-session-exporter", "--json"]

#: A probe that outlives this is not worth waiting for. Teardown is already
#: bounded by the caller, and a hung exporter must not extend it: the spool is
#: retained either way, so a missed probe costs a delayed verdict, not data.
_PROBE_TIMEOUT_SECONDS: Final = 30


class WorkspaceExecutor(Protocol):
    """Runs a command in the still-running workspace.

    Keyword-only `timeout_seconds`, matching the signature the real caller has
    (`execute(handle, command, *, timeout_seconds=...)`). An earlier version
    took it positionally. That type-checked fine here and would have raised
    TypeError at the one call site that matters, where the guard below would
    have swallowed it into UNKNOWN and scheduled a backfill on every single
    execution: silent, permanent, and self-concealing.
    """

    async def __call__(self, command: list[str], *, timeout_seconds: int) -> ExecutionResult: ...


async def probe_capture(
    execute: WorkspaceExecutor,
    *,
    expectations: CaptureExpectations | None,
    timeout_seconds: int = _PROBE_TIMEOUT_SECONDS,
) -> AuthoritativeCapture:
    """Run the exporter in the workspace and interpret what it says.

    Args:
        execute: Runs a command in the still-running container. Takes the argv
            and a timeout, returns an ExecutionResult.
        expectations: Where the caller meant the sessions to go, or None when
            no store is configured.
        timeout_seconds: Bound on the probe itself.

    Does not raise for operational capture errors: a probe that cannot answer
    returns a state that needs backfill, because "we could not find out" and
    "it is safely stored" must never be the same value. CancelledError
    propagates, because swallowing cancellation during teardown hangs shutdown.
    """
    if expectations is None:
        return AuthoritativeCapture(
            state=CaptureState.DISABLED, reason="no session store configured"
        )

    try:
        result = await execute(EXPORTER_PROBE_COMMAND, timeout_seconds=timeout_seconds)

        if result.timed_out:
            # The exporter did not finish, so whatever it managed to print is
            # not a verdict. FAILED rather than UNKNOWN because a timeout is a
            # known failure to complete, which is what CaptureState.FAILED
            # documents. Both request backfill, so this records the truth
            # rather than changing the recovery.
            return AuthoritativeCapture(
                state=CaptureState.FAILED,
                reason=f"capture probe timed out after {timeout_seconds}s",
            )

        return parse_capture_result(result.stdout, result.exit_code, expectations=expectations)
    except Exception as exc:
        # Deliberately broad, and deliberately wrapping the PARSE as well as
        # the call: a malformed result must not escape either. This runs during
        # teardown of a phase that may have SUCCEEDED, and no exporter problem
        # is worth converting that into a failure.
        #
        # CancelledError is a BaseException and is NOT caught here, on purpose.
        # Swallowing cancellation during teardown hangs shutdown, which is
        # worse than losing a verdict, and it matches what the isolation
        # provider's logs() does for the same reason.
        logger.warning("session-capture probe could not run: %s", exc)
        return AuthoritativeCapture(
            state=CaptureState.UNKNOWN,
            reason=f"capture probe could not run: {exc}",
        )
