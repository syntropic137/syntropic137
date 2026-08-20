"""Assemble the capture verdict: ask, interpret, record.

The three pieces already exist and are each independently testable. This binds
them into the one operation a caller wants, and owns the ordering constraint
that makes the answer trustworthy:

    while the container is still RUNNING
      -> the HOST runs the exporter                (capture_probe)
      -> the result is interpreted, not guessed    (capture_result)
      -> the verdict is recorded on Lane 2         (capture_observation)

WHY A SERVICE AND NOT INLINE. The caller is WorkflowExecutionProcessor, which
is domain code, and every piece here lives in the adapter layer. Injecting this
as a port keeps that boundary intact, and follows the pattern the processor
already uses for conversation storage.

NOTHING HERE CAN FAIL A PHASE. Capture is fail-open: a transcript that did not
reach the store must never turn an hour of successful agent work into a failed
one. The probe swallows operational errors, the recorder swallows write
failures, and this returns the verdict rather than raising on it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_adapters.workspace_backends.agentic.capture_observation import (
    build_expectations,
    record_capture_outcome,
)
from syn_adapters.workspace_backends.agentic.capture_probe import probe_capture
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_adapters.workspace_backends.agentic.session_store_env import build_partition

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.capture_observation import (
        ObservationWriter,
    )
    from syn_adapters.workspace_backends.agentic.capture_probe import WorkspaceExecutor
    from syn_adapters.workspace_backends.agentic.capture_result import (
        AuthoritativeCapture,
    )
    from syn_shared.settings.session_store import SessionStoreSettings

__all__ = ["SessionCapturePort", "SessionCaptureService"]

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
    """Runs the probe and records the verdict. Never raises."""

    def __init__(
        self,
        settings: SessionStoreSettings,
        app_environment: str,
        writer: ObservationWriter | None,
    ) -> None:
        self._settings = settings
        self._app_environment = app_environment
        self._writer = writer

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
        expectations = build_expectations(
            self._settings, self._app_environment, expect_sessions=expect_sessions
        )
        outcome = await probe_capture(execute, expectations=expectations)

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
