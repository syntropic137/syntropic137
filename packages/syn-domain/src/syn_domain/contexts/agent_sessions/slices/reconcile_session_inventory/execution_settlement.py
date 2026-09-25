"""Host settlement facts: execution terminal, then a bounded deadline (#1364).

Workflow executions belong to orchestration. This slice reads one field of its
terminal events through a consumer-side model rather than importing that
context's internals: ``extra="ignore"`` keeps working as those events grow.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    RunSettlementEvidence,
    RunSettlementStage,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidenceBatch

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.ports.SessionSettlementPort import SettlementDeadline

SETTLEMENT_PRODUCER = "syntropic-execution-settlement"
DEADLINE_BATCH = "settlement-deadline"


class ExecutionTerminalEventType(StrEnum):
    """Every orchestration event after which an execution never runs again."""

    COMPLETED = "WorkflowCompleted"
    FAILED = "WorkflowFailed"
    CANCELLED = "ExecutionCancelled"
    INTERRUPTED = "WorkflowInterrupted"


class ExecutionTerminal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    execution_id: str = ""


def settlement_batch(
    deadline: SettlementDeadline, stage: RunSettlementStage, batch_id: str
) -> EvidenceBatch:
    """Deterministic payload: replaying the same fact is a byte-equivalent retry."""
    reference = deadline.terminal.model_copy(
        update={
            "evidence_id": f"{SETTLEMENT_PRODUCER}:{batch_id}",
            "extractor_version": "host-execution-settlement/1",
        }
    )
    return EvidenceBatch(
        batch_id=batch_id,
        producer_id=SETTLEMENT_PRODUCER,
        evidence=SessionEvidence(
            run=deadline.run,
            run_settlement=(RunSettlementEvidence(stage=stage, evidence=reference),),
        ),
    )
