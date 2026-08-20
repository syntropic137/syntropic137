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

#: The exporter, by ABSOLUTE PATH.
#:
#: Resolving it through PATH was forgeable. /opt/agentic is agent-owned in the
#: workspace image, so the agent can edit the capability's init.sh to prepend a
#: directory of its own and have a fake exporter answer the audit. The binary
#: itself is root-owned 0755, so naming its path is what makes the program
#: producing the verdict the one the host intended.
EXPORTER_BIN: Final = "/usr/local/bin/apss-session-exporter"

#: Exit status when the workspace carries no session-store contract at all.
EXIT_NO_CAPABILITY: Final = 4

#: What a shell returns for "command not found", reused here for "the exporter
#: is not in this image". Kept because an image with no exporter reads as
#: DISABLED: there is no capture to audit, so a backfill would chase
#: transcripts that could never have existed.
EXIT_COMMAND_NOT_FOUND: Final = 127

#: The probe translates the capability contract ITSELF rather than sourcing the
#: adapter's init.sh.
#:
#: WHY, and this is the whole reason the wrapper exists in this shape: an audit
#: must not be configured by the party it audits. /opt/agentic is agent-owned,
#: so init.sh is agent-writable, and sourcing it hands the agent control of the
#: audit's environment. A PATH prepended with a fake exporter is the obvious
#: attack; the quieter one is SESSION_STORE_URL pointed at a sink the agent
#: controls, where the REAL exporter uploads faithfully and returns a clean
#: sweep for transcripts the store never saw.
#:
#: Every value below comes from the container's own configured environment,
#: which is set by the host at create time and is not writable from inside.
#: The mapping mirrors init.sh exactly - seven variables, verified against the
#: adapter in the pinned image. It is duplication, and the alternative is
#: trusting code the audited process can rewrite.
#:
#: The token is read from the container's environment rather than passed on the
#: command line, so it never appears in the host's argv.
_PROBE_SCRIPT: Final = f"""
BIN={EXPORTER_BIN}
[ -x "$BIN" ] || exit {EXIT_COMMAND_NOT_FOUND}
[ -n "${{AGENTIC_SESSION_STORE_URL:-}}" ] || exit {EXIT_NO_CAPABILITY}

SPOOL="${{AGENTIC_SESSION_STORE_SPOOL:-/spool}}"
PARTITION="${{AGENTIC_SESSION_STORE_PARTITION:-${{HOSTNAME}}}}"
PART_DIR="$SPOOL/$PARTITION"

export SESSION_STORE_URL="$AGENTIC_SESSION_STORE_URL"
export CLAUDE_PROJECTS_ROOT="$PART_DIR/claude"
export CODEX_SESSIONS_ROOT="$PART_DIR/codex"
export EXPORTER_STATE_FILE="$SYN_PROBE_STATE_FILE"

if [ -n "${{AGENTIC_SESSION_STORE_AUTH:-}}" ]; then
  export SESSIONS_WRITE_TOKEN="$AGENTIC_SESSION_STORE_AUTH"
fi
if [ -n "${{AGENTIC_SESSION_STORE_TAGS:-}}" ]; then
  export SESSION_STORE_TAGS="$AGENTIC_SESSION_STORE_TAGS"
fi
if [ -n "${{AGENTIC_SESSION_STORE_DEPLOYMENT:-}}" ]; then
  export SESSION_STORE_ORIGIN_DEPLOYMENT="$AGENTIC_SESSION_STORE_DEPLOYMENT"
fi

exec "$BIN" --ignore-state --json
"""

#: Plain sh: the script is POSIX and authored here, so it no longer depends on
#: the adapter's bash-only init.sh.
EXPORTER_PROBE_COMMAND: Final = ["sh", "-c", _PROBE_SCRIPT]

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
#: NOTE ON WHAT THIS DOES AND DOES NOT BUY. The path is host-SELECTED,
#: not host-owned: /tmp is a writable tmpfs, so the agent can create or
#: symlink this file. What stops its contents forging a verdict is
#: --ignore-state, which makes the exporter not read state at all. The
#: separate path remains worthwhile - it keeps the audit from disturbing
#: the capability's own state - but it is not a trust boundary.
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
