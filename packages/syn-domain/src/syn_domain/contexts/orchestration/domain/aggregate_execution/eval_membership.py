"""An execution's eval membership: which eval it belongs to, and how it joined (#967).

The execution owns this, not the eval: attaching a run is one write to the
run's own stream, and the eval's stream does not grow with every run.

An execution belongs to at most one eval at a time. It joins one of two ways,
its ``association_kind``:

- ``launched``: the launch chose the eval, recorded on ``WorkflowExecutionStarted``.
- ``attached``: it was added afterwards, by ``ExecutionAttachedToEval``, in any
  status. Reports use this to tell historical additions from planned runs.

``launched_eval_id`` is the launch record and survives a detach unchanged: the
run was launched into that eval whatever its membership says now. A re-attach
after a detach is ``attached``, even to the same eval, because the current
association was made after the fact.

The rules are decided here, so the aggregate's handlers only check the run
exists and apply what comes back. Whether the EVAL can take the run (exists, not
archived) is not decidable from this stream; the attach slice asks the Eval
aggregate after this decides the attach would record an event, so an attach
that changes nothing never asks it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from syn_domain.contexts.orchestration.domain.events.ExecutionAttachedToEvalEvent import (
    ExecutionAttachedToEvalEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionDetachedFromEvalEvent import (
    ExecutionDetachedFromEvalEvent,
)


class AssociationKind(StrEnum):
    """How an execution joined the eval it belongs to."""

    LAUNCHED = "launched"
    ATTACHED = "attached"


class EvalMembershipConflictError(ValueError):
    """The execution belongs to a different eval than the one a command names."""


@dataclass(frozen=True)
class EvalMembership:
    eval_id: str | None = None
    association_kind: AssociationKind | None = None
    launched_eval_id: str | None = None

    @classmethod
    def launched_into(cls, eval_id: str | None) -> EvalMembership:
        if eval_id is None:
            return cls()
        return cls(eval_id, AssociationKind.LAUNCHED, eval_id)

    def attach(
        self, eval_id: str, *, execution_id: str, workflow_id: str
    ) -> ExecutionAttachedToEvalEvent | None:
        """The event attaching to ``eval_id`` records, or None if already a member.

        Raises when the run belongs to another eval: detach it first.
        """
        if self.eval_id == eval_id:
            return None
        if self.eval_id is not None:
            msg = (
                f"Execution {execution_id} belongs to eval {self.eval_id}; "
                f"detach it before attaching it to {eval_id}"
            )
            raise EvalMembershipConflictError(msg)
        return ExecutionAttachedToEvalEvent(
            execution_id=execution_id,
            workflow_id=workflow_id,
            eval_id=eval_id,
            attached_at=datetime.now(UTC),
        )

    def detach(
        self, eval_id: str, *, execution_id: str, workflow_id: str
    ) -> ExecutionDetachedFromEvalEvent | None:
        """The event detaching from ``eval_id`` records, or None if in no eval.

        Raises when the run belongs to a different eval than ``eval_id``.
        """
        if self.eval_id is None or self.association_kind is None:
            return None
        if self.eval_id != eval_id:
            msg = f"Execution {execution_id} belongs to eval {self.eval_id}, not {eval_id}"
            raise EvalMembershipConflictError(msg)
        return ExecutionDetachedFromEvalEvent(
            execution_id=execution_id,
            workflow_id=workflow_id,
            eval_id=eval_id,
            association_kind=self.association_kind.value,
            detached_at=datetime.now(UTC),
        )

    def with_attached(self, eval_id: str) -> EvalMembership:
        return replace(self, eval_id=eval_id, association_kind=AssociationKind.ATTACHED)

    def detached(self) -> EvalMembership:
        return replace(self, eval_id=None, association_kind=None)
