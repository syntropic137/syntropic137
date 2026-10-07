"""Level 4: an execution request and its execution are two streams on the real store.

The ESP server keys a stream by aggregate id alone: `events` is keyed
`(tenant_id, aggregate_id, aggregate_nonce)` and the gRPC client sends only
the id half of `Type-id`. #1574 saved the request at its execution's own id,
so on the server `ExecutionRequested` became version 1 of
`WorkflowExecution-<id>`, the start's NoStream write conflicted, and every
direct start was dropped as a duplicate (v0.33.2-beta.8 and beta.9). The
in-memory client keys by the whole stream name and could not show it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository, RepositoryFactory

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _started(execution_id: str) -> WorkflowExecutionAggregate:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        StartExecutionCommand,
        WorkflowExecutionAggregate,
    )

    execution = WorkflowExecutionAggregate()
    execution._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-request-stream",
            workflow_name="Request Stream",
            total_phases=1,
            inputs={},
        )
    )
    return execution


class TestARequestDoesNotOccupyItsExecutionsStream:
    async def test_the_execution_starts_after_its_request_was_recorded(
        self,
        repository_factory: RepositoryFactory,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
        from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
            ExecutionRequestAggregate,
            execution_request_id,
        )
        from syn_domain.contexts.orchestration.domain.commands.RequestExecutionCommand import (
            RequestExecutionCommand,
        )

        execution_id = f"exec-{unique_execution_id}"
        requests = repository_factory.create_repository(
            ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "ExecutionRequest",
        )
        request = ExecutionRequestAggregate()
        request.request(
            RequestExecutionCommand(
                execution_id=execution_id,
                workflow_id="wf-request-stream",
                launch_eval=LaunchEval(None, EvalSelection.NONE),
            )
        )
        await requests.save_new(request)

        # The start's NoStream write, exactly as the processor makes it.
        await workflow_execution_repository.save_new(_started(execution_id))

        loaded_request = await requests.load(execution_request_id(execution_id))
        loaded_execution = await workflow_execution_repository.load(execution_id)
        assert loaded_request is not None
        assert loaded_request.workflow_id == "wf-request-stream"
        assert loaded_execution is not None
        assert loaded_execution.version == 1

    async def test_the_server_has_one_keyspace_for_every_aggregate_type(
        self,
        repository_factory: RepositoryFactory,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """The hazard itself: why a request must never take its execution's id.

        If ESP ever keys streams by type and id, this fails and the prefix in
        `execution_request_id` becomes optional rather than load-bearing.
        """
        from event_sourcing import StreamAlreadyExistsError

        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            WorkflowExecutionAggregate,
        )

        shared_id = f"exec-{unique_execution_id}"
        other_type = repository_factory.create_repository(
            WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "SomeOtherAggregate",
        )
        await other_type.save_new(_started(shared_id))

        with pytest.raises(StreamAlreadyExistsError):
            await workflow_execution_repository.save_new(_started(shared_id))


class TestAWithdrawalLivesOnTheRequestsOwnStream:
    async def test_it_round_trips_and_leaves_the_executions_id_free(
        self,
        repository_factory: RepositoryFactory,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """#1650: `ExecutionRequestWithdrawn` is stored, reloaded, and is not the execution's."""
        from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
        from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
            ExecutionRequestAggregate,
            execution_request_id,
        )
        from syn_domain.contexts.orchestration.domain.commands.RequestExecutionCommand import (
            RequestExecutionCommand,
        )
        from syn_domain.contexts.orchestration.domain.commands.WithdrawExecutionRequestCommand import (
            WithdrawExecutionRequestCommand,
        )

        execution_id = f"exec-{unique_execution_id}"
        requests = repository_factory.create_repository(
            ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "ExecutionRequest",
        )
        request = ExecutionRequestAggregate()
        request.request(
            RequestExecutionCommand(
                execution_id=execution_id,
                workflow_id="wf-request-stream",
                launch_eval=LaunchEval(None, EvalSelection.NONE),
            )
        )
        await requests.save_new(request)
        loaded = await requests.load(execution_request_id(execution_id))
        assert loaded is not None
        loaded.withdraw(WithdrawExecutionRequestCommand(execution_id=execution_id, reason="r"))
        await requests.save(loaded)

        reloaded = await requests.load(execution_request_id(execution_id))
        assert reloaded is not None
        assert reloaded.withdrawn
        assert reloaded.version == 2
        # The execution's own id is untouched by either request event.
        assert await workflow_execution_repository.load(execution_id) is None
