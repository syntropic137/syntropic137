"""What `run_phase_agent` hands back, and how many attempts it made getting there (#1303).

`busy_upstream` decides WHETHER a failure earns another attempt and is pinned in
`test_busy_upstream.py`. What is pinned here is everything that happens around
that decision: which attempt's result reaches the caller, which failures never
reach the policy at all, and what is built once versus once per attempt.

The last of those is the easiest to break and the hardest to see. The caller
gets one `AgentExecutionResult` and cannot count the attempts behind it, so a
retry that quietly started a fresh observability collector - losing the Lane-2
records of every attempt but the last, which is what the cost ledger reads -
would leave every assertion about the RESULT still passing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_attempts import (
    run_phase_agent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseLaunch
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_shared.agents import AgentProvider, AgentRunner

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration import AgentExecutionResult
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
    )

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

AT_CAPACITY = "codex reported: Selected model is at capacity. Please try a different model."
BAD_LOGIN = "Authentication failed"

#: Zero backoff, real bound. The schedule is asserted in `test_busy_upstream.py`;
#: serving it here would buy nothing and cost 15 seconds per test.
NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)


@dataclass
class _RecordedAttempt:
    """One call to the agent handler, kept whole so a test can compare attempts."""

    session_id: str
    timeout_seconds: int
    runner: Runner
    collector: ObservabilityCollector | None
    workspace: ManagedWorkspace


@dataclass
class _RecordingHandler:
    """Delegates to a scripted `FakeAgentExecutionHandler` and keeps every call.

    The fake records the todo and the runner; what is interesting here is the
    rest of the arguments, and specifically whether they are the SAME values
    on attempt three as on attempt one.
    """

    scripted: FakeAgentExecutionHandler
    attempts: list[_RecordedAttempt] = field(default_factory=list)

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        self.attempts.append(
            _RecordedAttempt(
                session_id=session_id,
                timeout_seconds=timeout_seconds,
                runner=runner,
                collector=collector,
                workspace=workspace,
            )
        )
        return await self.scripted.handle(
            todo,
            workspace,
            agent_env,
            claude_cmd,
            session_id,
            agent_model,
            timeout_seconds,
            collector,
            runner,
            on_launch,
        )


# pyright verifies the double still matches the real handler's contract.
_: AgentHandlerProtocol = _RecordingHandler(scripted=FakeAgentExecutionHandler.success())


def _phase(provider: str = AgentProvider.CLAUDE, timeout_seconds: int = 900) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="verify",
        name="Verify",
        order=3,
        agent_config=AgentConfiguration(provider=provider, timeout_seconds=1),
        prompt_template="do the thing",
        timeout_seconds=timeout_seconds,
    )


def _launch() -> PhaseLaunch:
    # The workspace is opaque to this unit - it is forwarded and never read -
    # so a sentinel is the honest double, and identity is what gets asserted.
    return PhaseLaunch(
        workspace=cast("ManagedWorkspace", object()),
        agent_env={"SYN_PHASE": "verify"},
        claude_cmd=["claude", "-p"],
        started_at=datetime.now(UTC),
        session_manager=None,
    )


async def _run(
    handler: _RecordingHandler,
    *,
    phase: ExecutablePhase | None = None,
    launch: PhaseLaunch | None = None,
) -> AgentExecutionResult:
    return await run_phase_agent(
        handler=handler,
        todo=TodoItem(
            action=TodoAction.RUN_AGENT,
            execution_id="exec-1",
            phase_id="verify",
            session_id="sess-1",
        ),
        phase=phase or _phase(),
        launch=launch or _launch(),
        session_id="sess-1",
        observability=None,
        retry_policy=NO_WAITING,
    )


class TestWhichResultTheCallerGets:
    async def test_a_later_attempt_that_succeeds_is_the_one_that_comes_back(self) -> None:
        """The first attempt's non-zero exit must not survive into the result.

        The caller treats whatever it receives as final and raises on a non-zero
        exit code, so returning attempt one here would fail the execution having
        paid for a successful attempt two.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(says="done"),
                ]
            )
        )

        result = await _run(handler)

        assert len(handler.attempts) == 2
        assert result.command.exit_code == 0
        assert result.stream_result.error_reason is None

    async def test_a_spent_budget_comes_back_with_the_reason_the_agent_gave(self) -> None:
        """Not a story about retrying. `_handle_run_agent` puts this string in
        the message an operator reads, so a retry that replaced it with its own
        summary would hide the cause of every exhausted failure."""
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler.failed(exit_code=1, reason=AT_CAPACITY)
        )

        result = await _run(handler)

        assert len(handler.attempts) == NO_WAITING.max_attempts == 3
        assert result.command.exit_code == 1
        assert result.stream_result.error_reason == AT_CAPACITY


class TestWhatNeverReachesThePolicy:
    async def test_a_run_that_exited_zero_is_not_attempted_again(self) -> None:
        """Even when it carries a capacity message on its stream.

        `_note_stream_fault` keeps the FIRST fault a harness reports and never
        clears it, so a turn that hit a busy upstream and a process that went on
        to exit zero leave a result with both. The exit code is then the only
        thing standing between a finished phase and two more runs of it, which
        is why the fixture carries the reason that would otherwise qualify - a
        success with `error_reason=None` would pass this test on the policy's
        refusal rather than on the rule under test.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(exit_code=0, reason=AT_CAPACITY)
        )

        result = await _run(handler)

        assert len(handler.attempts) == 1
        assert result.command.exit_code == 0

    async def test_a_cancelled_run_is_not_restarted_even_when_the_upstream_was_busy(
        self,
    ) -> None:
        """The ordering rule, and the only case where it is visible.

        A cancelled phase exits non-zero AND can carry a capacity reason, so if
        the interrupt were left to the signature list to sort out, `syn control
        cancel` would be answered by two more attempts at the work the operator
        just stopped.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(interrupt=True, exit_code=1, reason=AT_CAPACITY)
        )

        result = await _run(handler)

        assert len(handler.attempts) == 1
        assert result.stream_result.interrupt_requested

    async def test_a_failure_the_upstream_did_not_cause_is_not_retried(self) -> None:
        """A login that is not valid fails identically on attempt three, having
        spent the phase's budget three times.

        The reason the POLICY is asked about has to be this attempt's own. Ask
        it about anything else and every failure in the system becomes
        retryable, which is the failure mode that turns one lost phase into
        three.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler.failed(exit_code=1, reason=BAD_LOGIN)
        )

        result = await _run(handler)

        assert len(handler.attempts) == 1
        assert result.stream_result.error_reason == BAD_LOGIN


class TestWhatIsBuiltOncePerPhaseAndNotOncePerAttempt:
    async def test_every_attempt_reports_to_the_same_collector(self) -> None:
        """What a failed attempt spent is still spent.

        The collector is the Lane-2 record the cost ledger reads. Building one
        per attempt would leave a run that retried twice reporting only the
        third attempt's usage - understating a real bill, silently, in the one
        direction nobody goes looking.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        await _run(handler)

        first = handler.attempts[0].collector
        assert first is not None
        assert len(handler.attempts) == 3
        assert all(attempt.collector is first for attempt in handler.attempts)

    async def test_a_retry_runs_the_same_phase_in_the_same_workspace(self) -> None:
        """Same session, same container, same budget. A retry that re-resolved
        any of these would be a different run wearing the same phase id."""
        launch = _launch()
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        await _run(handler, phase=_phase(timeout_seconds=1234), launch=launch)

        assert len(handler.attempts) == 2
        assert [a.session_id for a in handler.attempts] == ["sess-1", "sess-1"]
        assert [a.timeout_seconds for a in handler.attempts] == [1234, 1234]
        assert all(a.workspace is launch.workspace for a in handler.attempts)


class TestTheProviderChoosesTheParser:
    @pytest.mark.parametrize(
        ("provider", "expected"),
        [(AgentProvider.CLAUDE, AgentRunner.CLAUDE), (AgentProvider.CODEX, AgentRunner.CODEX)],
    )
    async def test_the_runner_matches_the_phase_and_survives_a_retry(
        self, provider: str, expected: Runner
    ) -> None:
        """Resolved here now rather than in the processor. A retry handed the
        claude parser to a codex stream would report a phase that ran as one
        that produced nothing parseable."""
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        await _run(handler, phase=_phase(provider=provider))

        assert [a.runner for a in handler.attempts] == [expected, expected]
