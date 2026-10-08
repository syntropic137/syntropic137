"""PhaseCommitPushed event - a running phase's own workspace pushed a commit (PC-128)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("PhaseCommitPushed", "v1")
class PhaseCommitPushedEvent(DomainEvent):
    """The running phase's workspace pushed ``sha`` to ``branch`` on origin.

    Recorded while the phase runs, from the push hook in the phase's own
    workspace, because the one case it exists for never reaches the end of
    the phase: a deploy orphans the run after the agent pushed, and the
    failure that follows observes nothing.

    This IS an attribution, and a narrow one: the commit was in this
    phase's workspace and that workspace sent it to origin. It does not say
    the push landed or that origin still holds it - a resume asks the forge
    for that, and continues the branch only when its head is one of these
    SHAs (`branch_continuation.decide_continuation`). Contrast
    `BranchObservation`, which says a ref moved and deliberately not who
    moved it.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    #: The clone's directory name, as the push hook reports it.
    repository: str
    branch: str
    sha: str
    pushed_at: datetime
