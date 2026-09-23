"""PhaseRetryScheduled event - a phase's attempt is being given up and re-run."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("PhaseRetryScheduled", "v1")
class PhaseRetryScheduledEvent(DomainEvent):
    """One attempt at a phase ended recoverably; another is being started.

    NOT a failure of the phase and not a completion of it. The phase is still
    the execution's current phase, on the same execution, against the same
    inputs and the same repositories at the same commits - everything that
    decided what the last attempt would do is unchanged, because nothing about
    the execution changed. What is discarded is one attempt's workspace and one
    attempt's session; what is preserved is every phase before it (#1335).

    Its whole reason for existing is that the discarding has to survive a
    restart. The attempt count IS the retry budget, so holding it in the
    processor would hand a phase a fresh allowance every time the process
    bounced - the one shape that turns a bounded retry into a loop that bills.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    #: Which attempt is about to start, counting the original as 1. So the
    #: first retry records 2. Written as the number of the NEXT attempt rather
    #: than of the one that just died, because that is what a reader of the
    #: following `PhaseStarted` needs in order to place it.
    attempt: int
    #: What was wrong with the attempt being abandoned, in the words the
    #: failure would have been reported in had it not been retried. Recorded
    #: because a retry that becomes routine is a defect nobody is looking at,
    #: and this is the only place the reason would otherwise be visible.
    reason: str
    scheduled_at: datetime
