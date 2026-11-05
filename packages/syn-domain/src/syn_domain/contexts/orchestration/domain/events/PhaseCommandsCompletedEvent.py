"""PhaseCommandsCompleted event - a command Phase's steps have run (ADR-078 D5)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import (
    CommandStepResult,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("PhaseCommandsCompleted", "v1")
class PhaseCommandsCompletedEvent(DomainEvent):
    """A command Phase ran its fixed steps; this is what each one said.

    NOT `AgentExecutionCompleted` with zero tokens. A command Phase has no
    agent session, no provider and no model, and this event says so by not
    carrying them: every one of those fields on the agent event would be false
    here.

    Recorded whatever `success` says. The to-do list collects artifacts next in
    both cases, so a failed gate's logs are kept, and the aggregate decides at
    collection what a failure means (fail the Execution as `gate`). The step
    results are on the stream rather than in the processor because a restart
    between this event and collection loses the workspace, and must lose only
    the output tails with it, never the verdict (D6).
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    workspace_id: str
    completed_at: datetime
    success: bool
    #: The Phase's own deadline ran out. A step's own timeout is on the step.
    timed_out: bool = False
    steps: list[CommandStepResult]
