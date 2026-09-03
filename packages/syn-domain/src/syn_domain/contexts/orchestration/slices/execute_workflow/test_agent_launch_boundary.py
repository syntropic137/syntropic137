"""Where the "an agent ran" fact is allowed to come from (#1047, #1065).

The fact licenses one specific statement to a user - "this session never
started an agent, so there is no log" - so it may only be recorded by
something that can actually tell. These tests pin it to the process boundary:
the agent's own stream, consumed by the real handler, reporting into a real
SessionLifecycleManager.

The distinction they exist to hold is between an agent that was *dispatched*
and one that *existed*. Everything between those two - a dead container, a
missing binary, a refused exec - used to be invisible, because the launch was
recorded by the code that decided to dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.agent_sessions import AgentLaunch
from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
    TodoAction,
    TodoItem,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

_PROCESSOR_PATH = (
    "syn_domain.contexts.orchestration.slices.execute_workflow"
    ".handlers.AgentExecutionHandler.EventStreamProcessor"
)


class _ConsumingStreamProcessor:
    """Stream processor double that actually drains the stream.

    A double that ignored its argument would make every one of these tests
    pass without a process ever being simulated, which is the failure mode
    they are here to rule out.
    """

    def __init__(self, **_kwargs: object) -> None:
        self.lines: list[str] = []

    async def process_stream(self, stream: AsyncIterator[str], workspace: object) -> StreamResult:
        del workspace
        async for line in stream:
            self.lines.append(line)
        return StreamResult(
            line_count=len(self.lines),
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
        )


def _workspace(*, lines: list[str] | None = None, fails: bool = False) -> MagicMock:
    """A workspace whose stream either starts a process or cannot."""

    async def _stream(*_args: object, **_kwargs: object) -> AsyncIterator[str]:
        if fails:
            # Raised where the real adapter raises: at create_subprocess_exec,
            # before anything is yielded and before any exit code exists.
            raise RuntimeError("container is gone")
        for line in lines or []:
            yield line

    workspace = MagicMock()
    workspace.stream = _stream
    workspace.last_stream_exit_code = 0
    return workspace


async def _run_phase(workspace: MagicMock) -> SessionLifecycleManager:
    """Run one phase through the real handler and return its session manager."""
    session_mgr = SessionLifecycleManager(
        repository=AsyncMock(),
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="p-1",
        agent_provider="claude",
        agent_model="claude-haiku",
    )
    await session_mgr.start()

    with patch(_PROCESSOR_PATH, _ConsumingStreamProcessor):
        await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(
                execution_id="exec-1",
                action=TodoAction.RUN_AGENT,
                phase_id="p-1",
                session_id="sess-1",
            ),
            workspace=workspace,
            agent_env={},
            claude_cmd=["claude", "-p"],
            session_id="sess-1",
            agent_model="claude-haiku",
            timeout_seconds=300,
            on_launch=session_mgr.mark_launched,
        )
    return session_mgr


@pytest.mark.anyio
async def test_a_stream_that_never_starts_a_process_records_no_launch() -> None:
    """The break: dispatching an agent was treated as evidence one existed.

    Here the handler is reached, the command is built, the workspace is asked
    to stream - and the process is never created. The session must be able to
    say so, because this is the only shape that may be reported to a user as
    never having started.

    Move the signal back to the caller and this fails: the session is marked
    launched before the handler is ever entered, so nothing downstream can
    tell this case from an agent that ran.
    """
    session_mgr = SessionLifecycleManager(
        repository=AsyncMock(),
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="p-1",
        agent_provider="claude",
        agent_model="claude-haiku",
    )
    await session_mgr.start()

    with patch(_PROCESSOR_PATH, _ConsumingStreamProcessor), pytest.raises(RuntimeError):
        await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(
                execution_id="exec-1",
                action=TodoAction.RUN_AGENT,
                phase_id="p-1",
                session_id="sess-1",
            ),
            workspace=_workspace(fails=True),
            agent_env={},
            claude_cmd=["claude", "-p"],
            session_id="sess-1",
            agent_model="claude-haiku",
            timeout_seconds=300,
            on_launch=session_mgr.mark_launched,
        )

    session = session_mgr.session
    assert session is not None
    assert session.agent_launch is AgentLaunch.NOT_LAUNCHED


@pytest.mark.anyio
async def test_an_agent_that_dies_before_printing_anything_still_launched() -> None:
    """The mirror-image error: counting output instead of the process.

    An agent that starts and exits before its first line produces an empty
    stream, and calling that "never started" would be the same false statement
    in the other direction. The stream advancing at all is the evidence, not
    what it carried.
    """
    session_mgr = await _run_phase(_workspace(lines=[]))

    session = session_mgr.session
    assert session is not None
    assert session.agent_launch is AgentLaunch.LAUNCHED


@pytest.mark.anyio
async def test_a_streaming_agent_is_launched_and_its_output_is_untouched() -> None:
    """The wrapper is transparent: every line still reaches the processor."""
    processors: list[_ConsumingStreamProcessor] = []

    class _Recording(_ConsumingStreamProcessor):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            processors.append(self)

    session_mgr = SessionLifecycleManager(
        repository=AsyncMock(),
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="p-1",
        agent_provider="claude",
        agent_model="claude-haiku",
    )
    await session_mgr.start()

    with patch(_PROCESSOR_PATH, _Recording):
        result = await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(
                execution_id="exec-1",
                action=TodoAction.RUN_AGENT,
                phase_id="p-1",
                session_id="sess-1",
            ),
            workspace=_workspace(lines=['{"a": 1}', '{"b": 2}']),
            agent_env={},
            claude_cmd=["claude", "-p"],
            session_id="sess-1",
            agent_model="claude-haiku",
            timeout_seconds=300,
            on_launch=session_mgr.mark_launched,
        )

    session = session_mgr.session
    assert session is not None
    assert session.agent_launch is AgentLaunch.LAUNCHED
    assert processors[0].lines == ['{"a": 1}', '{"b": 2}']
    assert result.stream_result.line_count == 2
