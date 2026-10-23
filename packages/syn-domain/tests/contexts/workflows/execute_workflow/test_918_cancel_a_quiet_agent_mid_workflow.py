"""#918: cancelling a quiet agent stops the workflow, through the real processor.

The issue's run kept going: the cancel never stopped the agent, and every later
phase ran. This drives the real ``WorkflowExecutionProcessor`` over two phases
whose first agent says one line and then goes silent, the shape a cancel tied
to output could never see (verify B1). The user cancels only once it is quiet,
with no reason, as the API sends it.

Asserted at the boundaries that matter: the stream's ``cancel_running`` is what
ends the agent, phase 2 never starts, ``ExecutionCancelledEvent`` reaches the
repository's save, and the phase's workspace is destroyed by the production
cleanup, not by the test.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
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
    _two_phase_workflow,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = pytest.mark.unit

#: The production poll is 2s; a cancel must land within a couple of polls.
_BOUND_SECONDS = 10.0


class _QuietAgent(MemoryEventStreamAdapter):
    """Says one line, then nothing, until the provider cancels it.

    It ignores everything else: only ``cancel_running`` ends the stream, so a
    cancel that does not reach it leaves the phase running.
    """

    def __init__(self) -> None:
        super().__init__()
        self.started: list[str] = []
        self.spoke = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.cancelled_ids: list[str] = []

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> AsyncIterator[str]:
        self.started.append(handle.isolation_id)
        yield '{"type":"system","subtype":"init"}'
        self.spoke.set()
        await self.cancelled.wait()

    async def cancel_running(self, handle: IsolationHandle) -> bool:
        self.cancelled_ids.append(handle.isolation_id)
        self.cancelled.set()
        return True


class _UserCancelsLater:
    def __init__(self) -> None:
        self.pending = False

    async def check_signal(self, execution_id: str) -> ControlSignal | None:
        if not self.pending:
            return None
        return ControlSignal(signal_type=ControlSignalType.CANCEL, execution_id=execution_id)


@pytest.mark.anyio
async def test_a_cancel_stops_a_quiet_agent_and_no_later_phase_runs() -> None:
    agent = _QuietAgent()
    workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    workspace_service._event_stream = agent  # pyright: ignore[reportPrivateUsage]
    isolation = workspace_service._isolation  # pyright: ignore[reportPrivateUsage]
    destroyed: list[str] = []
    original_destroy = isolation.destroy

    async def recording_destroy(handle: IsolationHandle) -> None:
        destroyed.append(handle.isolation_id)
        await original_destroy(handle)

    isolation.destroy = recording_destroy  # pyright: ignore[reportAttributeAccessIssue]

    controller = _UserCancelsLater()
    processor = WorkflowExecutionProcessor(
        execution_repository=FakeExecutionRepository(),
        session_repository=FakeSessionRepository(),
        workspace_service=workspace_service,
        artifact_repository=FakeArtifactRepository(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=controller,  # pyright: ignore[reportArgumentType]
        prompt_builder=_noop_prompt_builder,
        command_builder=_noop_command_builder,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=None,
    )
    repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
    saved: list[str] = []
    original_save = repository.save

    async def capturing_save(aggregate: object) -> None:
        saved.extend(type(e.event).__name__ for e in aggregate.get_uncommitted_events())  # pyright: ignore[reportAttributeAccessIssue]
        await original_save(aggregate)

    repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

    run = asyncio.create_task(
        processor.run(
            workflow_id="wf-918-quiet",
            workflow_name="Cancelled while the agent was quiet",
            phases=_two_phase_workflow(first_declares=()),
            inputs={},
            execution_id="exec-918-quiet",
        )
    )
    async with asyncio.timeout(_BOUND_SECONDS * 3):
        await agent.spoke.wait()
        await asyncio.sleep(2.5)  # past a poll: quiet, not cancelled, still running
        assert not run.done()
        assert not agent.cancelled.is_set()
        controller.pending = True
        loop = asyncio.get_running_loop()
        cancelled_at = loop.time()
        result = await run
    took = loop.time() - cancelled_at

    assert result.status == "cancelled"
    assert took < _BOUND_SECONDS, f"cancel took {took:.1f}s"
    assert len(agent.started) == 1, f"a later phase ran after the cancel: {agent.started}"
    assert agent.cancelled_ids == agent.started, "the cancel did not reach the running agent"
    assert saved.count("ExecutionCancelledEvent") == 1, saved
    assert agent.started[0] in destroyed, "the cancelled phase's workspace was left behind"
