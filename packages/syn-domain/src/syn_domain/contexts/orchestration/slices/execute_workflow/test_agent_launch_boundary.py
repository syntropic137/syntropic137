"""Where the "an agent ran" fact is allowed to come from (#1047, #1065).

The fact licenses one specific statement to a user - "this session never
started an agent, so there is no log" - so it may only be recorded by
something that can actually tell. These tests pin it to the process boundary:
the agent's own announcement, carried on its stream, consumed by the real
handler and recorded through a real SessionLifecycleManager.

The distinction they exist to hold is between an agent that was *dispatched*
and one that *existed*. Everything between those two - a dead container, a
missing binary, a refused exec - is invisible to anything that watches the
transport rather than the process.

These are the domain half of that boundary, and they take the announcement as
given. That the real `docker exec` transport emits it exactly when a process
was created, and that its own failure diagnostics do not, is the adapter's
half: ``syn-adapters/tests/workspace_backends/agentic/test_agent_launch_evidence.py``
drives the real adapter against real `docker exec` failure shapes to prove it.
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
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AGENT_LAUNCH_MARKER,
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

#: What the client prints when the container it was pointed at is gone. It
#: reaches the handler as an ordinary line, because `docker exec` merges its
#: own stderr into the agent's stdout - which is what made "a line arrived"
#: unusable as evidence.
_CLIENT_DIAGNOSTIC = "Error response from daemon: No such container: agentic-ws-abc123"

#: What the wrapper shell prints when the announcement it just made turns out
#: to be false. It arrives on the same stream as agent output and cannot be
#: told apart from it by looking, which is why the exit status rather than the
#: line decides.
_EXEC_FAILED = "syn-launch: 1: exec: /usr/local/bin/claude: not found"


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


def _workspace(
    *, lines: list[str] | None = None, raises: bool = False, exit_code: int = 0
) -> MagicMock:
    """A workspace whose stream produces the given lines, or cannot start at all.

    ``exit_code`` is what the process carrying the stream reports afterwards -
    the wrapper shell's own status when it never managed to exec the agent, and
    the agent's own status once it did.
    """

    async def _stream(*_args: object, **_kwargs: object) -> AsyncIterator[str]:
        if raises:
            raise RuntimeError("docker is not installed")
        for line in lines or []:
            yield line

    workspace = MagicMock()
    workspace.stream = _stream
    workspace.last_stream_exit_code = exit_code
    return workspace


def _session_manager() -> SessionLifecycleManager:
    return SessionLifecycleManager(
        repository=AsyncMock(),
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="p-1",
        agent_provider="claude",
        agent_model="claude-haiku",
    )


async def _run_phase(
    workspace: MagicMock,
    session_mgr: SessionLifecycleManager,
    processor: type[_ConsumingStreamProcessor] = _ConsumingStreamProcessor,
) -> None:
    """Run one phase through the real handler, reporting into ``session_mgr``."""
    with patch(_PROCESSOR_PATH, processor):
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


def _launch_of(session_mgr: SessionLifecycleManager) -> AgentLaunch:
    session = session_mgr.session
    assert session is not None
    return session.agent_launch


@pytest.mark.anyio
@pytest.mark.parametrize(
    "lines",
    [[], [_CLIENT_DIAGNOSTIC]],
    ids=["nothing at all", "a client diagnostic"],
)
async def test_a_stream_with_no_announcement_records_no_launch(lines: list[str]) -> None:
    """The break: something arriving on the stream was treated as a process.

    Both of these are a transport reporting its own failure. One says so and
    one does not, and neither ran anything inside the container - so neither
    may license the statement that gets made to a user about a session that
    did not launch.
    """
    session_mgr = _session_manager()
    await session_mgr.start()

    await _run_phase(_workspace(lines=lines), session_mgr)

    assert _launch_of(session_mgr) is AgentLaunch.NOT_LAUNCHED


@pytest.mark.anyio
async def test_a_stream_that_cannot_start_records_no_launch() -> None:
    """Nothing was reached at all, and the failure still has to reach the caller."""
    session_mgr = _session_manager()
    await session_mgr.start()

    with pytest.raises(RuntimeError):
        await _run_phase(_workspace(raises=True), session_mgr)

    assert _launch_of(session_mgr) is AgentLaunch.NOT_LAUNCHED


@pytest.mark.anyio
async def test_an_agent_that_dies_before_printing_anything_still_launched() -> None:
    """The mirror-image error: counting output instead of the process.

    An agent that starts and exits before its first line produces a stream
    carrying nothing but its own announcement, and calling that "never
    started" would be the same false statement in the other direction.
    """
    session_mgr = _session_manager()
    await session_mgr.start()

    await _run_phase(_workspace(lines=[AGENT_LAUNCH_MARKER]), session_mgr)

    assert _launch_of(session_mgr) is AgentLaunch.LAUNCHED


@pytest.mark.anyio
async def test_a_streaming_agent_is_launched_and_its_output_is_untouched() -> None:
    """Transparent otherwise: every real line reaches the processor, the marker does not.

    The announcement is evidence, not content. Leaving it in the stream would
    hand a line of non-JSON to a JSONL parser on every single phase.
    """
    processors: list[_ConsumingStreamProcessor] = []

    class _Recording(_ConsumingStreamProcessor):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            processors.append(self)

    session_mgr = _session_manager()
    await session_mgr.start()

    await _run_phase(
        _workspace(lines=[AGENT_LAUNCH_MARKER, '{"a": 1}', '{"b": 2}']),
        session_mgr,
        processor=_Recording,
    )

    assert _launch_of(session_mgr) is AgentLaunch.LAUNCHED
    assert processors[0].lines == ['{"a": 1}', '{"b": 2}']


@pytest.mark.anyio
@pytest.mark.parametrize("exit_code", [126, 127], ids=["not executable", "not found"])
async def test_an_announcement_the_exec_did_not_follow_records_no_launch(
    exit_code: int,
) -> None:
    """The hop the whole fix hangs on (#1065).

    The wrapper announces immediately before ``exec``, so this stream carries a
    perfectly genuine marker - and then the exec failed, and the shell that
    announced is still there to say so with the status only it can return. The
    handler has to carry that status into the launch fact; a version that
    settled on the marker alone, or that read the status and dropped it before
    the session manager, passes every other test in this file.
    """
    session_mgr = _session_manager()
    await session_mgr.start()

    await _run_phase(
        _workspace(lines=[AGENT_LAUNCH_MARKER, _EXEC_FAILED], exit_code=exit_code),
        session_mgr,
    )

    assert _launch_of(session_mgr) is AgentLaunch.NOT_LAUNCHED


@pytest.mark.anyio
async def test_an_agent_that_ran_and_failed_is_still_launched() -> None:
    """The line the retraction must not cross.

    Agents fail. An agent that started, worked and exited non-zero has
    demonstrably existed, and reporting it as never-started is the same false
    statement as #1047, just reached from the other side. Only the two statuses
    that mean the exec itself did not happen retract, and this is not one.
    """
    session_mgr = _session_manager()
    await session_mgr.start()

    await _run_phase(
        _workspace(lines=[AGENT_LAUNCH_MARKER, '{"type": "result"}'], exit_code=1),
        session_mgr,
    )

    assert _launch_of(session_mgr) is AgentLaunch.LAUNCHED


@pytest.mark.anyio
async def test_a_cancelled_phase_keeps_the_launch_its_agent_earned() -> None:
    """The stream nobody drained, which is where deferring the answer could lose it.

    Cancellation breaks out of the processor's loop mid-stream, so the process
    is never waited on and the status still on the workspace belongs to some
    earlier phase - here a failed exec's 127, the worst thing it could be. A
    settle that read it anyway would tell the user this session never started
    an agent that it had just interrupted.
    """
    session_mgr = _session_manager()
    await session_mgr.start()

    class _StopsAtTheFirstLine(_ConsumingStreamProcessor):
        async def process_stream(
            self, stream: AsyncIterator[str], workspace: object
        ) -> StreamResult:
            del workspace
            async for line in stream:
                self.lines.append(line)
                break
            return StreamResult(
                line_count=len(self.lines),
                interrupt_requested=True,
                interrupt_reason="cancelled",
                agent_task_result=None,
            )

    await _run_phase(
        _workspace(lines=[AGENT_LAUNCH_MARKER, '{"a": 1}', '{"b": 2}'], exit_code=127),
        session_mgr,
        processor=_StopsAtTheFirstLine,
    )

    assert _launch_of(session_mgr) is AgentLaunch.LAUNCHED
