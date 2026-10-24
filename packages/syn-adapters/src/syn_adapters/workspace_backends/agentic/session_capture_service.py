"""Assemble the capture verdict: ask, interpret, record.

The three pieces already exist and are each independently testable. This binds
them into the one operation a caller wants. It REQUIRES the ordering below but
cannot enforce it: only the layer holding the workspace context manager can
prove the probe ran before teardown.

    while the container is still RUNNING
      -> the HOST runs the exporter                (capture_probe)
      -> the result is interpreted, not guessed    (capture_result)
      -> the verdict is recorded on Lane 2         (capture_observation)

WHY A SERVICE AND NOT INLINE. The caller is WorkflowExecutionProcessor, which
is domain code, and every piece here lives in the adapter layer. Injecting this
as a port keeps that boundary intact, and follows the pattern the processor
already uses for conversation storage.

CAPTURE MUST NOT FAIL A PHASE. Capture is fail-open: a transcript that did not
reach the store must never turn an hour of successful agent work into a failed
one. The probe absorbs operational errors, the recorder absorbs write failures,
and this returns the verdict rather than raising on it. Cancellation is the one
exception and propagates deliberately, because swallowing it during teardown
hangs shutdown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_adapters.workspace_backends.agentic.capability_start import (
    SESSION_STORE_CAPABILITY,
)
from syn_adapters.workspace_backends.agentic.capture_observation import (
    build_expectations,
    record_capture_outcome,
)
from syn_adapters.workspace_backends.agentic.capture_probe import probe_capture
from syn_adapters.workspace_backends.agentic.capture_result import AuthoritativeCapture
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_adapters.workspace_backends.agentic.session_store_env import build_partition

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.capability_start import (
        CapabilityStatusReader,
        StartCapability,
    )
    from syn_adapters.workspace_backends.agentic.capture_observation import (
        ObservationWriter,
    )
    from syn_adapters.workspace_backends.agentic.capture_probe import WorkspaceExecutor
    from syn_shared.settings.session_store import SessionStoreSettings

__all__ = ["SessionCapturePort", "SessionCaptureService", "explain_degraded_start"]

logger = logging.getLogger(__name__)


class SessionCapturePort(Protocol):
    """What the processor needs, expressed without naming the adapter."""

    async def capture_and_record(
        self,
        execute: WorkspaceExecutor,
        *,
        session_id: str,
        execution_id: str,
        workspace_id: str,
        phase_id: str,
        expect_sessions: bool,
    ) -> AuthoritativeCapture: ...


class SessionCaptureService:
    """Runs the probe and records the verdict.

    Absorbs capture and recording failures. Cancellation propagates.
    """

    def __init__(
        self,
        settings: SessionStoreSettings,
        app_environment: str,
        writer: ObservationWriter | None,
        *,
        capability_reader: CapabilityStatusReader,
    ) -> None:
        self._settings = settings
        self._app_environment = app_environment
        self._writer = writer
        self._capability_reader = capability_reader

    async def capture_and_record(
        self,
        execute: WorkspaceExecutor,
        *,
        session_id: str,
        execution_id: str,
        workspace_id: str,
        phase_id: str,
        expect_sessions: bool,
    ) -> AuthoritativeCapture:
        """Ask the exporter, interpret the answer, record it.

        Must be called while the container is still running. Once it is
        stopped there is nothing to exec into, and once removed the spool is
        gone with it.

        Returns the verdict so a caller can act on it, and records it either
        way. The return value is deliberately not an error channel: a capture
        that did not happen is telemetry, not a phase failure.
        """
        # A configured store is NOT the same as a workspace that received
        # one: only the agentic backend injects the session-store environment,
        # and only images carrying the exporter can act on it.
        #
        # That fact is DERIVED from the container rather than passed in. An
        # earlier version took a capture_provisioned flag from the caller, which
        # made a false negative both possible and silent: a workspace that
        # really was provisioned would record nothing at all, and nothing would
        # indicate that capture had been skipped. The exporter already reports
        # its own configuration, so the workspace is asked instead of trusted.
        #
        # The DISABLED verdicts this produces are still recorded. "Capture is
        # off here" is exactly what the indicator exists to show, and it does
        # not request a backfill, so it costs a row and cries no wolf.
        expectations = build_expectations(
            self._settings, self._app_environment, expect_sessions=expect_sessions
        )
        # The start verdict is read here, not at workspace start: the row was
        # written by the entrypoint before the agent ran and does not change
        # afterwards, and this is the one hook that already holds the running
        # container. Only asked when a store is configured, because with none
        # there is no capability and no row (#1516).
        start = (
            await self._capability_reader.read(execute, SESSION_STORE_CAPABILITY)
            if expectations is not None
            else None
        )
        outcome = explain_degraded_start(
            await probe_capture(execute, expectations=expectations), start
        )

        await record_capture_outcome(
            self._writer,
            outcome,
            session_id=session_id,
            expectations=expectations,
            # The same partition the capability was told to spool into, so a
            # retry can find the transcripts by the identity that produced
            # them rather than by reconstructing one.
            partition=build_partition(execution_id, workspace_id),
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
            start_capability=start,
        )

        if outcome.needs_backfill:
            # Worth a log line as well as an observation: an operator watching
            # a run should not have to query telemetry to learn that a session
            # may be missing from the corpus.
            logger.warning(
                "session capture %s for execution %s phase %s: %s",
                outcome.state.value,
                execution_id,
                phase_id,
                outcome.reason or "no reason given",
            )
        elif outcome.state is not CaptureState.DISABLED:
            logger.info(
                "session capture %s for execution %s phase %s",
                outcome.state.value,
                execution_id,
                phase_id,
            )

        return outcome


def explain_degraded_start(
    outcome: AuthoritativeCapture, start: StartCapability | None
) -> AuthoritativeCapture:
    """Read a capture loss after a degraded start as DEGRADED, not unexplained.

    A workspace that started with the session store disabled captures nothing
    by design, so the probe then reports it as failed, incomplete or even
    disabled - the last of which would not be recorded at all. Each of those
    hides the cause the entrypoint already wrote down. A CAPTURED verdict is
    left alone: the host-side exporter's evidence of a stored session outranks
    a start-time prediction that there would be none.
    """
    if start is None or not start.degraded or outcome.state is CaptureState.CAPTURED:
        return outcome
    checks = ", ".join(start.failed_checks) or "unspecified checks"
    return outcome.model_copy(
        update={
            "state": CaptureState.DEGRADED,
            "reason": (
                f"session store degraded at workspace start ({checks} failed, "
                f"doctor exit {start.doctor_exit}); capture was disabled"
            ),
        }
    )
