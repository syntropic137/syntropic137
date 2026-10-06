"""ExecutionRequest aggregate root (#1557).

Location: orchestration/domain/aggregate_execution_request/ (per ADR-020).

The durable record that a direct start (`POST /workflows/{id}/execute`) was
admitted. Written before the caller is told 200, so an accepted start that is
still waiting for an execution-budget slot survives a restart: the
`ExecutionRequestStartProcessManager` starts it from this record.

Its own stream, at `execution_request_id(execution_id)`, and never the
execution's: the execution stream still opens with NoStream when the start
runs, which is what refuses a second start of the same request.

Never the execution id itself. The event store keys a stream by aggregate id
alone (`events` is keyed `(tenant_id, aggregate_id, aggregate_nonce)`; the
aggregate type is not part of a stream's identity), so a request saved at the
execution's id IS version 1 of `WorkflowExecution-<id>`, the start's NoStream
write conflicts, and the run is dropped as a duplicate dispatch. That shipped
in #1574 and stopped every direct start on v0.33.2-beta.8 and beta.9.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_choice import (
    EvalChoice,
    EvalSelection,
    LaunchEval,
)
from syn_domain.contexts.orchestration._shared.repository_baseline import RepositoryBaseline
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        EvalBaselinePin,
    )
    from syn_domain.contexts.orchestration.domain.commands.RequestExecutionCommand import (
        RequestExecutionCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionRequestedEvent import (
        ExecutionRequestedEvent,
    )


class ExecutionAlreadyRequestedError(ValueError):
    """An execution id is requested once."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"Execution {execution_id} was already requested")


@aggregate("ExecutionRequest")
class ExecutionRequestAggregate(AggregateRoot["ExecutionRequestedEvent"]):
    """One admitted direct start. Command handlers decide; event handlers record."""

    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._workflow_id: str | None = None
        self._inputs: dict[str, str] = {}
        self._task: str | None = None
        self._repos: tuple[RepositoryRef, ...] = ()
        self._tags: TagSet = TagSet()
        self._requested_at: datetime | None = None
        self._eval_choice: EvalChoice = EvalChoice()
        self._launch_eval: LaunchEval | None = None

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    @property
    def workflow_id(self) -> str | None:
        return self._workflow_id

    @property
    def requested_at(self) -> datetime | None:
        return self._requested_at

    @property
    def inputs(self) -> dict[str, str]:
        return dict(self._inputs)

    @property
    def task(self) -> str | None:
        return self._task

    @property
    def repos(self) -> list[RepositoryRef]:
        return list(self._repos)

    @property
    def tags(self) -> TagSet:
        return self._tags

    @property
    def launch_eval(self) -> LaunchEval | None:
        """The eval this start joins, resolved at acceptance (#967); never re-resolved.

        None only for a request recorded before requests carried their
        resolved eval. Such a request holds just its launch's ``eval_choice``,
        which its start resolves once, as every launch did before #967.
        """
        return self._launch_eval

    @property
    def eval_choice(self) -> EvalChoice:
        """What the launch asked for. Read only when ``launch_eval`` is None."""
        return self._eval_choice

    @command_handler("RequestExecutionCommand")
    def request(self, command: RequestExecutionCommand) -> None:
        from syn_domain.contexts.orchestration.domain.events.ExecutionRequestedEvent import (
            ExecutionRequestedEvent,
        )

        if self.id is not None:
            raise ExecutionAlreadyRequestedError(str(self.id))
        self._initialize(command.aggregate_id)
        launch = command.launch_eval
        self._apply(
            ExecutionRequestedEvent(
                execution_id=command.execution_id,
                workflow_id=command.workflow_id,
                inputs=dict(command.inputs),
                task=command.task,
                repos=[r.slug for r in command.repos],
                tags=list(command.tags),
                eval_id=None if launch.eval_id is None else str(launch.eval_id),
                eval_ordinary=launch.selection is EvalSelection.ORDINARY,
                eval_selection=launch.selection.value,
                eval_baseline=_baseline_pins(launch),
                requested_at=datetime.now(UTC),
            )
        )

    @event_sourcing_handler("ExecutionRequested")
    def on_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        self._workflow_id = event.workflow_id
        self._inputs = dict(event.inputs)
        self._task = event.task
        self._repos = tuple(RepositoryRef.from_slug(r) for r in event.repos)
        self._tags = TagSet.recorded(event.tags)
        self._requested_at = event.requested_at
        eval_id = EvalId.recorded(event.eval_id) if event.eval_id is not None else None
        if event.eval_selection is None:
            # Recorded before requests carried their resolved eval: `eval_id`
            # is only what the launch named, and its start resolves the choice.
            self._eval_choice = EvalChoice(eval_id=eval_id, ordinary=event.eval_ordinary)
            return
        self._launch_eval = LaunchEval(
            eval_id,
            EvalSelection(event.eval_selection),
            tuple(
                RepositoryBaseline(
                    repository=RepositoryRef.from_slug(pin.repository),
                    requested_ref=pin.requested_ref,
                    commit_sha=pin.commit_sha,
                )
                for pin in event.eval_baseline or ()
            ),
        )


def _baseline_pins(launch: LaunchEval) -> list[EvalBaselinePin] | None:
    """The admitted eval's frozen baseline as the event records it; None in no eval."""
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        EvalBaselinePin,
    )

    if launch.eval_id is None:
        return None
    return [
        EvalBaselinePin(
            repository=pin.repository.slug,
            requested_ref=pin.requested_ref,
            commit_sha=pin.commit_sha,
        )
        for pin in launch.baseline
    ]
