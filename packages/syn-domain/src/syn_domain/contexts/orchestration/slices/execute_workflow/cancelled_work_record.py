"""Tell a cancelled execution's stream what its save landed, and keep trying (#1547).

THE EVENT IS THE ONLY WAY THE PR HEARS. `CancelledWorkQuarantined` is what the
quarantine notice is posted from, and by the time this runs the cancel itself
is already on the stream - so a rejected append is not "the cancel failed", it
is a landed ref that nobody will ever be told about. Logging that and returning
a normal cancelled result was the defect: the refs exist, the fact does not.

So a rejection is retried, against the stream as the store now holds it. The
usual rejection is a version conflict - something else appended to this
execution after the processor last loaded it - and retrying the SAME aggregate
would only be refused again; reloading takes the newer version and asks the
aggregate again, which still owns the rule. A write that reached the store and
only failed to project is done: the event exists, and the to-do list being
behind is not the PR's problem.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    EventsNotRecordedError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordCancelledWorkCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )

logger = logging.getLogger(__name__)

#: Appends attempted before the landed refs are reported as untold. A module
#: global read at call time, so a test can count attempts without the tuning.
_ATTEMPTS: Final[int] = 3


async def record_cancelled_work(
    aggregate: WorkflowExecutionAggregate,
    command: RecordCancelledWorkCommand,
    *,
    journal: ExecutionJournal,
) -> bool:
    """Append ``command``'s landed refs to the execution's stream; True once they are durable."""
    target: WorkflowExecutionAggregate | None = aggregate
    for attempt in range(1, _ATTEMPTS + 1):
        if target is None:
            break
        try:
            target.record_cancelled_work(command)
            await journal.append(target)
        except EventsNotRecordedError:
            logger.warning(
                "Attempt %d/%d to record the quarantined work of cancelled execution %s "
                "was rejected by the event store; reloading and retrying",
                attempt,
                _ATTEMPTS,
                command.aggregate_id,
                exc_info=True,
            )
            target = await journal.reload(command.aggregate_id)
            continue
        except Exception:
            # Recorded; only this run's local to-do list did not take it.
            logger.exception(
                "Quarantined work of cancelled execution %s was recorded but not projected",
                command.aggregate_id,
            )
        return True
    logger.error(
        "The quarantined work of cancelled execution %s was NOT recorded, so its PR will "
        "not be told. The refs exist and are named in the cancel reason: %s",
        command.aggregate_id,
        ", ".join(ref.ref for ref in command.quarantined),
    )
    return False
