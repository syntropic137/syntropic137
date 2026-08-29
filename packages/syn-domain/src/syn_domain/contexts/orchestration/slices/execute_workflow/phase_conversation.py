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
    model: str | None,
    started_at: datetime,
) -> None:
    """Persist the phase's conversation lines alongside its totals."""
    recorder = ConversationRecorder(storage)
    await recorder.store(
        session_id=session_id,
        lines=result.stream_result.conversation_lines,
        execution_id=execution_id,
        phase_id=phase_id,
        workflow_id=workflow_id,
        model=model,
        input_tokens=result.tokens.input_tokens,
        output_tokens=result.tokens.output_tokens,
        started_at=started_at,
        success=result.command.exit_code == 0,
    )
