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

A store that refuses every attempt is not the end of it either. The refs are
then OWED: written to a store of their own, keyed by execution and phase, and
appended by the next `settle()` - which the processor runs at the start of
every run, and the quarantine notice manager on every live pass and clock
tick, so a store that comes back, or a process that restarts, delivers them
with no later execution needed. Owed is removed only once the event is on the stream, so the fact is
recoverable from one of the two places at every moment in between. A delete
that fails after the append leaves the row to be settled again, and the
aggregate records a cancel's work once, so that second append adds nothing.

When BOTH stores refuse, `record` says so and the processor's result carries
the refs as `unrecorded_work`. The cancel is not reported as handled. The
command is then held by this ledger, the last place left, and the next
`settle()` tries the stream and then the owed store again. The ledger is
process memory, so a restart before then loses what it holds. That is why the
API's `execute()` turns `unrecorded_work` into an `Err` naming every ref: with
both stores refusing there is nowhere durable left to write, and the failure
has to be loud rather than a normal cancelled result.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordCancelledWorkCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    QuarantinedRef,  # noqa: TC001 - a field type pydantic resolves at runtime
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    EventsNotRecordedError,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )

logger = logging.getLogger(__name__)

#: Appends attempted before the landed refs are owed instead. A module global
#: read at call time, so a test can count attempts without the tuning.
_ATTEMPTS: Final[int] = 3

#: Where owed refs wait for the stream to take them.
OWED_CANCELLED_WORK: Final[str] = "owed_cancelled_work"


class OwedCancelledWork(BaseModel):
    """Landed refs the event store refused, kept until it takes them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    phase_id: str
    quarantined: tuple[QuarantinedRef, ...]

    @property
    def key(self) -> str:
        return f"{self.execution_id}:{self.phase_id}"

    def as_command(self) -> RecordCancelledWorkCommand:
        return RecordCancelledWorkCommand(self.execution_id, self.phase_id, self.quarantined)


class CancelledWorkLedger:
    """Gets a cancelled execution's landed refs onto its stream, now or on a later run."""

    def __init__(self, journal: ExecutionJournal, owed: ProjectionStore | None) -> None:
        self._journal = journal
        self._owed = owed
        #: Refused by the stream AND the owed store; retried by `settle()`.
        self._unrecorded: list[RecordCancelledWorkCommand] = []

    async def record(
        self, aggregate: WorkflowExecutionAggregate, command: RecordCancelledWorkCommand
    ) -> bool:
        """Put the refs on the stream, or owe them; False when neither store took them."""
        if await self._append(aggregate, command) or await self._owe(command):
            return True
        self._unrecorded.append(command)
        return False

    async def settle(self) -> int:
        """Append every held and owed record the store now takes; the number appended."""
        settled = await self._settle_unrecorded()
        if self._owed is None:
            return settled
        try:
            rows = await self._owed.get_all(OWED_CANCELLED_WORK)
        except Exception:
            logger.exception("Could not read the owed quarantined work of cancelled executions")
            return settled
        for row in rows:
            owed = OwedCancelledWork.model_validate(row)
            aggregate = await self._reload(owed.execution_id)
            if aggregate is None or not await self._append(aggregate, owed.as_command()):
                continue
            settled += 1
            try:
                await self._owed.delete(OWED_CANCELLED_WORK, owed.key)
            except Exception:
                # Settled again next run; the aggregate makes that a no-op.
                logger.exception("Could not clear the owed work of execution %s", owed.key)
        return settled

    async def _settle_unrecorded(self) -> int:
        held, self._unrecorded = self._unrecorded, []
        settled = 0
        for command in held:
            aggregate = await self._reload(command.aggregate_id)
            if aggregate is not None and await self._append(aggregate, command):
                settled += 1
            elif not await self._owe(command):
                self._unrecorded.append(command)
        return settled

    async def _append(
        self, aggregate: WorkflowExecutionAggregate, command: RecordCancelledWorkCommand
    ) -> bool:
        target: WorkflowExecutionAggregate | None = aggregate
        for attempt in range(1, _ATTEMPTS + 1):
            if target is None:
                break
            try:
                target.record_cancelled_work(command)
            except ValueError:
                # The aggregate refused it, which is not "recorded": keep it owed.
                logger.exception("Execution %s refused its cancelled work", command.aggregate_id)
                return False
            try:
                await self._journal.append(target)
            except EventsNotRecordedError:
                logger.warning(
                    "Attempt %d/%d to record the quarantined work of cancelled execution %s "
                    "was rejected by the event store; reloading and retrying",
                    attempt,
                    _ATTEMPTS,
                    command.aggregate_id,
                    exc_info=True,
                )
                target = await self._reload(command.aggregate_id)
                continue
            except Exception:
                # Recorded; only this run's local to-do list did not take it.
                logger.exception(
                    "Quarantined work of cancelled execution %s was recorded but not projected",
                    command.aggregate_id,
                )
            return True
        return False

    async def _reload(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        try:
            return await self._journal.reload(execution_id)
        except Exception:
            logger.warning("Could not reload execution %s", execution_id, exc_info=True)
            return None

    async def _owe(self, command: RecordCancelledWorkCommand) -> bool:
        owed = OwedCancelledWork(
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            quarantined=command.quarantined,
        )
        refs = ", ".join(ref.ref for ref in command.quarantined)
        try:
            if self._owed is None:
                raise RuntimeError("no store for owed cancelled work is wired")
            await self._owed.save(OWED_CANCELLED_WORK, owed.key, owed.model_dump(mode="json"))
        except Exception:
            # Both stores refused. Only this process holds the refs now.
            logger.exception(
                "The quarantined work of cancelled execution %s was NOT recorded and could "
                "not be owed; it is held until the next run in this process. The refs exist: %s",
                command.aggregate_id,
                refs,
            )
            return False
        logger.error(
            "The event store refused the quarantined work of cancelled execution %s; it is "
            "owed and will be appended by the next run: %s",
            command.aggregate_id,
            refs,
        )
        return True
