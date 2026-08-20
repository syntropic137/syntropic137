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

WHAT THIS STILL CANNOT PROVE. The probe verifies that the exporter ran, where
it sent things, and that it lost nothing it SAW. It cannot verify that what the
exporter saw is everything that existed. An agent that deletes one of its two
transcripts leaves a sweep reporting `discovered=1` with no losses, which is
honest and incomplete. Closing that needs a host-known set of expected session
identities to compare against, which the host does not currently have. Tracked
rather than papered over: `expect_sessions` closes total deletion only.

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

__all__ = [
    "EXPORTER_PROBE_COMMAND",
    "PROBE_STATE_FILE",
    "WorkspaceExecutor",
    "probe_capture",
]

logger = logging.getLogger(__name__)

#: Where the workspace image keeps its capability adapters.
CAPABILITY_ROOT: Final = "/opt/agentic/capabilities/session-store"

#: Provider directory names to try, most current first.
#:
#: `apss` is the vendor-neutral name; `seshmagic` is the legacy alias kept as a
#: symlink beside it. Both are tried because an image pinned by digest may
#: predate the rename - the omni image running today has only `seshmagic` - and
#: a probe that assumed either name alone would report a capture failure on
#: every phase of the images it could not match.
CAPABILITY_PROVIDER_DIRS: Final = ("apss", "seshmagic")

#: Exit status the wrapper uses when it finds no capability to source.
#: Distinct from the exporter's own codes so it cannot be read as a verdict.
EXIT_NO_CAPABILITY: Final = 4

#: The probe runs the exporter THROUGH the capability's own init.sh.
#:
#: WHY, and this is the whole point of the wrapper: a fresh `docker exec`
#: inherits the container's configured AGENTIC_SESSION_STORE_* variables but
#: NOT what init.sh exported into PID 1. The exporter reads neither - it reads
#: the translated SESSION_STORE_* names that init.sh produces. Invoking the
#: binary directly therefore judged an exporter that had never been configured,
#: which returned "missing required env var SESSION_STORE_URL" and made every
#: phase report FAILED and request a backfill, forever (#852).
#:
#: init.sh is re-entrant: sourcing it from a fresh exec restores the URL, the
#: token, the tags and the deployment, verified against the pinned image.
#:
#: EXPORTER_STATE_FILE IS SET AFTER THE SOURCE, DELIBERATELY. init.sh exports
#: its own, inside the agent-writable spool. Letting that win would undo the
#: reason the host chooses this path at all - see PROBE_STATE_FILE below.
_PROBE_SCRIPT: Final = f"""
for d in {" ".join(CAPABILITY_PROVIDER_DIRS)}; do
  init="{CAPABILITY_ROOT}/$d/init.sh"
  if [ -f "$init" ]; then
    . "$init" >/dev/null 2>&1 || true
    EXPORTER_STATE_FILE="$SYN_PROBE_STATE_FILE" exec apss-session-exporter --json
  fi
done
exit {EXIT_NO_CAPABILITY}
"""

#: BASH, not sh. /bin/sh in the workspace image is dash, and init.sh is
#: bash-specific: under dash it dies with `Syntax error: "(" unexpected` before
#: exporting anything. The probe then produced NO output at all and no verdict,
#: which is the quietest possible way for this to fail.
EXPORTER_PROBE_COMMAND: Final = ["bash", "-c", _PROBE_SCRIPT]

#: Where the probe points the exporter's state file.
#:
#: NOT the capability's own state file, which lives under the agent-writable
#: spool. That file records which transcripts the exporter believes it has
#: already sent, and `skipped_unchanged` is derived from it. An agent that
#: marks an unstored transcript as current makes an honest exporter report
#: `discovered=1 skipped_unchanged=1` with every loss counter at zero, which
#: reads as a clean sweep. The host chooses who runs the exporter, but that is
#: worth nothing if the evidence it reads is writable by the thing being
#: audited.
#:
#: A path under /tmp, which the security profile mounts as its own tmpfs, is
#: outside the spool the agent owns. Starting from empty means the probe
#: re-evaluates every transcript rather than trusting a claim about them; the
#: store deduplicates on content hash, so re-sending an already-stored session
#: is a no-op rather than a duplicate.
PROBE_STATE_FILE: Final = "/tmp/.apss-probe-state.json"

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

    async def __call__(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult: ...


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
        result = await execute(
            EXPORTER_PROBE_COMMAND,
            timeout_seconds=timeout_seconds,
            # Passed under our own name, not EXPORTER_STATE_FILE: init.sh
            # exports that one itself, and whichever assignment ran last would
            # win. The wrapper applies this AFTER sourcing, so the host value
            # is the one the exporter sees.
            environment={"SYN_PROBE_STATE_FILE": PROBE_STATE_FILE},
        )

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

        if result.exit_code == EXIT_NO_CAPABILITY:
            # The image has no session-store adapter to source. UNKNOWN, not
            # DISABLED: a store IS configured for this workspace, so the
            # transcripts were expected to go somewhere. Calling it DISABLED
            # would close the case on sessions nobody has, and CAPTURED would
            # be a lie. UNKNOWN asks for the backfill and says why.
            return AuthoritativeCapture(
                state=CaptureState.UNKNOWN,
                reason=(
                    "no session-store capability found in this workspace image; "
                    "the probe could not reproduce the finalizer's environment"
                ),
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
