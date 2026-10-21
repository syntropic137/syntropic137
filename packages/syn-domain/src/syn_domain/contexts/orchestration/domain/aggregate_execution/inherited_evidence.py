"""An open evidence gate as a resume inherits it (plan §A.7, PR 5c).

A gate is open when its parent recorded `EvidenceRequested` and the gate never
opened: no `NextPhaseReady` followed. The parent's `ExecutionResumed` carries
it, the child's `WorkflowExecutionStarted` carries it on in `resumed_from`, and
the child seeds its own gate from it, so the child's last settle releases the
phase the parent held.

A value object, not the replayed `EvidenceGate`, because an event carries it
and an event may import only value objects. `EvidenceGate.inherited()` and
`EvidenceGate.resumed()` are the two directions; nothing else converts.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    ManifestStep,  # noqa: TC001 - needed at runtime for Pydantic
    PatchRemoval,  # noqa: TC001 - needed at runtime for Pydantic
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    EvidencePlanStep,  # noqa: TC001 - needed at runtime for Pydantic
)


class InheritedAttempt(BaseModel):
    """The parent's last attempt at a step it never settled.

    What the child needs to look for that run before posting another one
    (§A.7 3): the nonce in the run's name, when it was posted, and the run
    itself if the parent had already adopted it. Its deadline is deliberately
    absent: a person-started resume is a new decision, with a new deadline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int
    dispatch_id: str
    started_at: datetime
    run_id: int | None = None
    run_url: str | None = None


class InheritedEvidenceGate(BaseModel):
    """The parent's open gate: its plan and everything already settled in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    after_phase_id: str
    next_phase_id: str
    next_phase_order: int
    skipped_phase_ids: tuple[str, ...] = ()
    plan: tuple[EvidencePlanStep, ...]
    #: Settled steps in the manifest's shape (PR 1); ``head_sha`` is the head
    #: the step's run evidenced, as `EvidenceStepSettled` recorded it.
    settled: tuple[ManifestStep, ...] = ()
    patch_removal: PatchRemoval | None = None
    attempts: tuple[InheritedAttempt, ...] = ()

    @property
    def first_unsettled(self) -> int:
        """The step the child runs first. An inherited gate is open, so there is one."""
        done = {s.index for s in self.settled}
        return next(s.index for s in self.plan if s.index not in done)
