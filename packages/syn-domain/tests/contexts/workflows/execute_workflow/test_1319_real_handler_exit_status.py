"""#1319: an exit status nobody observed must be recorded as unknown, not as 0.

WHAT THE #1330 TESTS COULD NOT SEE. Every existing #1319 test drives
``FakeAgentExecutionHandler.failed(exit_code=...)``, which builds an
``AgentExecutionCompletedCommand`` with the status handed to it. That bypasses
the production stream and ``_detect_exit_code`` entirely - which is to say it
bypasses the only code that DECIDES a status - so it could assert that a number
survives the journey while the function that picks the number was returning 0
for "no idea".

And it was. ``ManagedWorkspace.last_stream_exit_code`` is None whenever no
stream status was ever completed, and a container removed out from under the
run is exactly that case. It fell through to ``return 0``: the situation we
know LEAST about became indistinguishable from a clean exit, on the durable
record an operator reads.

So these use the REAL ``AgentExecutionHandler``, over a stream double that ends
the way an externally removed container ends - reporting nothing. The claim is
about what the event store holds afterwards: ``exit_code`` present and None,
and no ``AgentExecutionCompleted`` claiming 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

from .test_processor_smoke import (
    FakeArtifactRepository,
    FakeExecutionRepository,
    _noop_command_builder,
    _noop_prompt_builder,
    _one_phase_workflow,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = pytest.mark.unit

#: The statuses that distinguish outcomes, and neither is reachable by accident:
#: 124 is the timeout wrapper's, -11 a SIGSEGV kill (#1295). A default or a
#: truthiness slip yields 0, 1 or None - never either of these.
TIMED_OUT = 124
SEGFAULTED = -11

#: What the workspace reports when no stream status was ever completed. The
#: container was removed out from under the run, so there is nothing left to
#: ask - the fixture value the old code could not tell from a clean exit.
NOTHING_OBSERVED = None


class _StreamEndingWith(MemoryEventStreamAdapter):
    """A stream that ends reporting `status`, or reporting nothing at all.

    The memory adapter always finishes by setting its exit code to 0, which is
    the one value that cannot demonstrate anything here. This overrides the end
    of the stream and nothing else: `None` leaves `last_exit_code` unset, which
    is precisely the shape `ManagedWorkspace.last_stream_exit_code` takes when
    the container is gone before it could be asked.
    """

    def __init__(self, status: int | None) -> None:
        super().__init__()
        self._status = status

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
    ) -> AsyncIterator[str]:
        for line in self._streams.get(handle.isolation_id, []):
            yield line
        self._last_exit_code = self._status


def _processor_over(stream: MemoryEventStreamAdapter) -> WorkflowExecutionProcessor:
    """A processor whose agent handler is the REAL one, streaming through `stream`.

    ``agent_handler=None`` is what makes this test worth writing: the processor
    then builds an ``AgentExecutionHandler`` per call, exactly as production
    does, so `_detect_exit_code` and the command it feeds are under test rather
    than stubbed over.
    """
    workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    workspace_service._event_stream = stream  # pyright: ignore[reportPrivateUsage]

    return WorkflowExecutionProcessor(
        execution_repository=FakeExecutionRepository(),
        session_repository=FakeSessionRepository(),
        workspace_service=workspace_service,
        artifact_repository=FakeArtifactRepository(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_noop_prompt_builder,
        command_builder=_noop_command_builder,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=None,
    )


class _Run:
    """What one execution recorded: its status, and every event it committed."""

    def __init__(self, status: str, events: list[object]) -> None:
        self.status = status
        self.events = events

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        """Every event of `event_type`, serialized as production serializes it.

        Read off the wire form rather than the objects, because a field present
        on a model and absent from its payload passes every object-level
        assertion and is still unrecoverable from the store.
        """
        return [
            ExecutionJournal._serialize_event(e)  # pyright: ignore[reportPrivateUsage]
            for e in self.events
            if type(e).__name__ == event_type
        ]


async def _run_a_phase_whose_stream_ends_with(status: int | None) -> _Run:
    """Run a one-phase workflow through the real handler and collect its events."""
    processor = _processor_over(_StreamEndingWith(status))

    # The repository clears uncommitted events on save (as the real SDK one
    # does), so they are taken as they go past rather than afterwards.
    repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
    recorded: list[object] = []
    original_save = repository.save

    async def capturing_save(aggregate: object) -> None:
        recorded.extend(e.event for e in aggregate.get_uncommitted_events())  # pyright: ignore[reportAttributeAccessIssue]
        await original_save(aggregate)

    repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

    result = await processor.run(
        workflow_id="wf-1319-real",
        workflow_name="Exit status decided by the real handler",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id=f"exec-1319-real-{status}",
    )
    return _Run(result.status, recorded)


class TestAStatusNobodyObservedIsRecordedAsUnknown:
    """The externally-removed-container case, which used to read as success."""

    @pytest.mark.anyio
    async def test_the_workflow_fails_rather_than_completing(self) -> None:
        """A phase whose exit nobody saw has not been shown to have succeeded.

        Before this, the run COMPLETED: `_detect_exit_code` returned 0, the
        processor's `exit_code != 0` guard never fired, and the phase was
        reported as a clean pass to every consumer downstream of it.
        """
        run = await _run_a_phase_whose_stream_ends_with(NOTHING_OBSERVED)

        assert run.status == "failed", (
            f"a phase whose exit status nobody observed must not be completed; got {run.status!r}"
        )

    @pytest.mark.anyio
    async def test_the_durable_event_carries_none_and_not_zero(self) -> None:
        """None is the honest answer and the only one that prompts a retry.

        The field must be PRESENT and null, not absent and not 0: an operator
        querying this needs to see that the status was asked for and unknown.
        """
        run = await _run_a_phase_whose_stream_ends_with(NOTHING_OBSERVED)

        failed = run.of_type("WorkflowFailedEvent")
        assert len(failed) == 1, f"expected exactly one WorkflowFailedEvent, got {len(failed)}"
        assert "exit_code" in failed[0], "the status must reach the wire, not just the model"
        assert failed[0]["exit_code"] is None, (
            f"an unobserved exit status must be recorded as unknown; got {failed[0]['exit_code']!r}"
        )
        assert failed[0]["error_type"] == "ExitStatusUnavailableError", (
            "the failure must say the status was unavailable, not name some later symptom"
        )

    @pytest.mark.anyio
    async def test_no_event_ever_claims_the_agent_completed_with_zero(self) -> None:
        """The lie has to be unreachable, not merely overwritten downstream.

        ``AgentExecutionCompleted`` is the event that carries a phase's exit
        status into the read model. Emitting it with 0 here would put "exited
        cleanly" on the stream permanently, whatever the workflow-level event
        says afterwards.
        """
        run = await _run_a_phase_whose_stream_ends_with(NOTHING_OBSERVED)

        completed = run.of_type("AgentExecutionCompletedEvent")
        assert completed == [], (
            f"no completion may be claimed for an unobserved exit; got {completed}"
        )


class TestAnObservedStatusIsRecordedExactly:
    """The counterpart: when the number IS known, it must survive unchanged."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("status", [TIMED_OUT, SEGFAULTED])
    async def test_a_non_zero_exit_reaches_the_workflow_failed_event(self, status: int) -> None:
        """124 and -11 demand opposite responses, so both must arrive intact."""
        run = await _run_a_phase_whose_stream_ends_with(status)

        assert run.status == "failed"
        failed = run.of_type("WorkflowFailedEvent")
        assert len(failed) == 1
        assert failed[0]["exit_code"] == status
        assert failed[0]["failed_phase_id"] == "phase-001", (
            "a status is only actionable attached to the phase it belongs to"
        )

    @pytest.mark.anyio
    async def test_an_explicit_zero_still_completes_the_phase(self) -> None:
        """0 is accepted - but only when the stream actually reported 0.

        This is the case the change must NOT break, and the reason the None
        case above is a real distinction rather than a blanket refusal.
        """
        run = await _run_a_phase_whose_stream_ends_with(0)

        assert run.status != "failed", f"an explicit 0 is a clean exit; got {run.status!r}"
        completed = run.of_type("AgentExecutionCompletedEvent")
        assert len(completed) == 1, "a phase that exited 0 reports its completion"
        assert completed[0]["exit_code"] == 0
