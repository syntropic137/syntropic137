"""Ask a workspace whether its transcripts reached the store, before teardown.

Lives beside the processor rather than inside it for two reasons. The processor
is already over its size budget, and this is a genuinely separable step: it
reads no processor state, decides nothing about the execution, and its only
tie to the phase is the identity it stamps on the observation.

The ORDERING is not separable, and stays at the call site: the probe must run
while the container is up. See `test_capture_before_teardown.py`, which asserts
the exec happens before `__aexit__`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import (
        ManagedWorkspace,
    )

__all__ = ["capture_phase_session"]

logger = logging.getLogger(__name__)


async def capture_phase_session(
    capture: SessionCapturePort | None,
    workspace: ManagedWorkspace | None,
    *,
    session_id: str,
    phase_id: str,
) -> None:
    """Record whether this phase's session was captured.

    Fail-open by construction: capture is telemetry, and a phase that did an
    hour of successful agent work must not be failed by a transcript that did
    not land. The service absorbs its own errors; this guards only the two
    cases where there is nothing to ask.
    """
    if capture is None or workspace is None:
        return

    # An observation keyed to "" is attributed to no session and cannot be
    # acted on: it neither identifies a transcript to backfill nor tells an
    # operator which run lost one. Refusing to write it, loudly, is better
    # than a row that looks like data. Reaching here without a session id
    # means a phase was torn down before _handle_run_agent recorded one, so
    # the agent had not started and there is nothing to have captured.
    if not session_id:
        logger.warning(
            "Skipping session capture for phase %s: no session id was recorded "
            "for it, so any observation would be attributed to no session.",
            phase_id,
        )
        return

    # The service absorbs its own operational failures, so this catches what
    # it cannot: a programming error in the capture path, or an adapter that
    # raises before the service's own guard runs. Either would otherwise
    # propagate into teardown and fail a phase whose agent work succeeded,
    # which is the one outcome capture must never cause.
    #
    # Exception, not BaseException: cancellation MUST keep propagating, or a
    # shutdown hangs waiting on a probe.
    try:
        await _record(capture, workspace, session_id=session_id, phase_id=phase_id)
    except Exception:
        logger.exception("Session capture failed for phase %s; continuing with teardown", phase_id)


async def _record(
    capture: SessionCapturePort,
    workspace: ManagedWorkspace,
    *,
    session_id: str,
    phase_id: str,
) -> None:
    await capture.capture_and_record(
        workspace.execute,
        session_id=session_id,
        execution_id=workspace.execution_id,
        workspace_id=workspace.workspace_id,
        phase_id=phase_id,
        # The agent ran, so a workspace that captures should have produced a
        # transcript. This is what turns an honest empty sweep into a reported
        # gap rather than a silent success.
        expect_sessions=True,
    )
