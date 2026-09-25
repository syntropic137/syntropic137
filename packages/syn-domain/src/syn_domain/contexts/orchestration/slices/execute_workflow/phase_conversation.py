"""Storing a phase's conversation transcript.

Split out of the processor, which is an orchestrator: this is one step with one
job, and keeping it here is part of the split ``fitness-exceptions.toml`` has
been asking for on WorkflowExecutionProcessor (#768).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.ConversationRecorder import (
    ConversationRecorder,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_adapters.conversations import ConversationStoragePort
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )

__all__ = ["record_phase_conversation"]


async def record_phase_conversation(
    storage: ConversationStoragePort | None,
    result: AgentExecutionResult,
    *,
    session_id: str,
    execution_id: str,
    phase_id: str,
    workflow_id: str,
    requested_model: str | None,
    started_at: datetime,
) -> None:
    """Persist the phase's conversation lines alongside its totals.

    Stored AFTER the stream ended, so the model the harness announced is
    known here and is what is filed as ``model``; the phase's declared model
    (often an alias) travels separately as ``requested_model`` (ADR-067).
    """
    recorder = ConversationRecorder(storage)
    await recorder.store(
        session_id=session_id,
        lines=result.stream_result.conversation_lines,
        execution_id=execution_id,
        phase_id=phase_id,
        workflow_id=workflow_id,
        model=result.stream_result.announced_model,
        requested_model=requested_model,
        input_tokens=result.tokens.input_tokens,
        output_tokens=result.tokens.output_tokens,
        started_at=started_at,
        # The run's own status, not the completion's. This runs BEFORE the
        # processor decides the phase outcome, so on a cancelled run there is no
        # completion to ask - and asking one anyway is how a cancelled phase came
        # to be filed as a success (#1341). None is not 0, so it is not a success.
        success=result.exit_code == 0,
    )
