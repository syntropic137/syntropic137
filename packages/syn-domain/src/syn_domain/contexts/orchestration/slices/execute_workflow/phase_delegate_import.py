"""Connecting a phase's capture verdict to the delegate import (#895).

Sits beside :mod:`phase_capture`, which produces the input this consumes: the
probe names the session ids the store confirmed, and this prices the ones the
platform did not already bill.

Separate from the processor because the processor is an orchestrator - it
decides what happens next - and this is a step. Keeping the payload shaping
here also keeps the domain module free of the telemetry schema.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.delegate_import import import_phase_delegates
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_capture import (
    capture_phase_session,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.agentic.capture_result import (
        AuthoritativeCapture,
    )
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import (
        ManagedWorkspace,
    )
    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.transcript_usage import PricedUsage
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
        StreamResult,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "DelegateUsageRecorder",
    "capture_and_import_phase",
    "close_phase_workspaces",
    "remember_leader_native_id",
]


class DelegateUsageRecorder:
    """Shapes a recovered delegate cost into a TOKEN_USAGE observation.

    Lives here rather than in the domain module because this is the layer that
    already knows the observation payload's field names. Keeping that knowledge
    on one side of the seam means a telemetry-schema rename breaks loudly here
    instead of silently unpricing delegates.
    """

    def __init__(self, writer: ObservabilityRecorder) -> None:
        self._writer = writer

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: PricedUsage | None,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None:
        # Zeroes carrying a reason, never an omission: an unpriceable delegate
        # has to stay visible as a gap rather than vanish into "never ran".
        data = {
            "input_tokens": usage.uncached_input_tokens if usage else 0,
            "output_tokens": usage.output_tokens if usage else 0,
            "cache_creation_tokens": usage.cache_creation_tokens if usage else 0,
            "cache_read_tokens": usage.cache_read_tokens if usage else 0,
            "model": usage.model if usage else None,
            "delegated": True,
            # Only present when there IS a reason, so its presence alone marks
            # a delegate that could not be priced.
            **({"unpriced_reason": unpriced_reason} if unpriced_reason else {}),
        }

        await self._writer.record_observation(
            session_id=session_id,
            observation_type=ObservationType.TOKEN_USAGE,
            data=data,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )


async def import_delegates_for_phase(
    capture: AuthoritativeCapture | None,
    *,
    session_store: SessionStorePort | None,
    writer: ObservabilityRecorder | None,
    leader_native_session_id: str | None,
    phase_id: str,
    execution_id: str,
    workspace_id: str | None = None,
) -> None:
    """Price the sessions this phase produced that nobody billed.

    Runs on the SAME two paths capture does - normal finalisation and
    teardown after a cancel or failure - because a phase that was cancelled
    still ran delegates, and their cost is exactly as real as a completed
    phase's. Carving that out would leave a class of executions quietly
    understated.

    Fail-open, like capture: an import that cannot run leaves the phase's
    own cost intact and unchanged. It must never turn agent work that
    succeeded into a phase that failed.
    """
    # Both are optional on the processor, so they are checked rather than
    # assumed: with no store there is nothing to read and with no writer there
    # is nowhere to record it, and calling through would raise inside a
    # teardown path that must not fail a phase.
    if session_store is None or writer is None or capture is None:
        return

    captured_ids = capture.agent_session_ids or ()
    if not captured_ids:
        return

    try:
        outcome = await import_phase_delegates(
            session_store,
            DelegateUsageRecorder(writer),
            leader_native_session_id=leader_native_session_id,
            captured_session_ids=captured_ids,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
            # One pass here. The sweep already CONFIRMED these sessions
            # reached the store, so a read that misses is a race measured
            # in tenths of a second rather than a wait worth holding a
            # phase open for; anything still unreadable is written as a
            # named gap instead.
            attempts_remaining=0,
        )
    except Exception:
        logger.exception(
            "Delegate import failed for phase %s; phase cost stands unchanged", phase_id
        )
        return

    if outcome.leader_missing_from_sweep:
        # Loud on purpose. The leader's id came off its own stream and the
        # sweep confirmed the session set, so a mismatch means one of those
        # two contracts moved - and every id is then a candidate, so
        # importing anything would risk billing the leader twice.
        logger.error(
            "Delegate import refused for phase %s: the leader's session id is not among "
            "the %d captured ids, so delegates cannot be told from the leader. "
            "No delegate cost was imported for this phase.",
            phase_id,
            len(captured_ids),
        )
        return

    if outcome.imported:
        logger.info(
            "Imported %d delegate session(s) for phase %s (%d priced)",
            len(outcome.imported),
            phase_id,
            sum(1 for d in outcome.imported if d.priced),
        )


async def capture_and_import_phase(
    capture_port: SessionCapturePort | None,
    workspace: ManagedWorkspace | None,
    *,
    session_store: SessionStorePort | None,
    writer: ObservabilityRecorder | None,
    leader_native_session_id: str | None,
    session_id: str,
    phase_id: str,
) -> None:
    """Probe for this phase's sessions, then price the ones nobody billed.

    One function because the two are one step with one ordering rule: both must
    happen while the container is still up. The processor calls this from the
    finalise path AND the cancel/failure path, and having a single entry point
    is what stops those two drifting - a cancelled phase that skipped the
    import would be understated in a way nothing downstream could detect.
    """
    capture = await capture_phase_session(
        capture_port, workspace, session_id=session_id, phase_id=phase_id
    )
    await import_delegates_for_phase(
        capture,
        session_store=session_store,
        writer=writer,
        leader_native_session_id=leader_native_session_id,
        phase_id=phase_id,
        execution_id=getattr(workspace, "execution_id", "") or "",
        workspace_id=getattr(workspace, "id", None),
    )


async def close_phase_workspaces(
    context: str,
    *,
    workspace_cms: dict[str, AbstractAsyncContextManager[ManagedWorkspace]],
    workspaces: dict[str, ManagedWorkspace],
    session_ids: dict[str, str],
    leader_native_ids: dict[str, str],
    capture_port: SessionCapturePort | None,
    session_store: SessionStorePort | None,
    writer: ObservabilityRecorder | None,
) -> None:
    """Probe, import, then tear down every still-open phase workspace.

    The cancel and failure path. A phase that never reached finalisation still
    ran an agent, and a failed run is the one whose transcript is most worth
    having - so the probe and the import both happen here too, in the same
    order and before the container goes away.
    """
    for phase_id, workspace_cm in list(workspace_cms.items()):
        await capture_and_import_phase(
            capture_port,
            workspaces.get(phase_id),
            session_store=session_store,
            writer=writer,
            leader_native_session_id=leader_native_ids.get(phase_id),
            session_id=session_ids.get(phase_id, ""),
            phase_id=phase_id,
        )
        try:
            await workspace_cm.__aexit__(None, None, None)
        except Exception:
            logger.exception("Error cleaning up workspace during %s", context)

    workspace_cms.clear()
    session_ids.clear()
    leader_native_ids.clear()


def remember_leader_native_id(
    leader_native_ids: dict[str, str],
    phase_id: str,
    stream_result: StreamResult,
) -> None:
    """Record the id this phase's own harness announced, if it announced one.

    A blank or absent id is not stored. Storing one would make every phase that
    announced nothing share a single key, and the import would then subtract
    the wrong session from the sweep.
    """
    announced = stream_result.leader_native_session_id
    if announced:
        leader_native_ids[phase_id] = announced
