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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import (
        ManagedWorkspace,
    )

__all__ = ["capture_phase_session"]


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
