"""EvidenceStepSettled event - one planned step reached its outcome (plan §A.4)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    StepOutcome,  # noqa: TC001 - needed at runtime for Pydantic
    StepRef,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("EvidenceStepSettled", "v1")
class EvidenceStepSettledEvent(DomainEvent):
    """The fact that moves a gate on. The last one opens it.

    Reports are artifacts referenced by id, never inlined.
    ``manifest_artifact_id`` is set on the last step only, and None there
    when the manifest could not be stored (fails closed, §A.6).
    """

    execution_id: str
    gate_id: str
    step: int
    outcome: StepOutcome
    reason: str | None = None
    run_id: int | None = None
    run_url: str | None = None
    head_sha_evidenced: str | None = None
    reused_from: StepRef | None = None
    report_artifact_ids: list[str] = Field(default_factory=list)
    manifest_artifact_id: str | None = None
