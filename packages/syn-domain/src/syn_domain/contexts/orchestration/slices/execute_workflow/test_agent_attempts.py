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

Two of those "what is built once" facts are budgets rather than objects, and
they are the ones a retry is most likely to spend twice: the phase's DEADLINE,
which every attempt and backoff comes out of, and the question of whether the
attempt that failed had already got somewhere, which is the only thing making
a rerun of the same prompt in the same workspace idempotent. Both are driven
here on a clock the test owns, because a 3600-second budget asserted against
the real clock costs 3600 seconds to assert.
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
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseLaunch
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_domain.testing.fake_clock import FakeClock
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

#: Spelled by the function that spells it in production. A literal would pass
#: this file and miss the real string the day the prefix changed.
AT_CAPACITY = codex_fault_reason("Selected model is at capacity. Please try a different model.")
BAD_LOGIN = "Authentication failed"

#: Zero backoff, real bound. The schedule is asserted in `test_busy_upstream.py`;
#: serving it here would buy nothing and cost 15 seconds per test.
NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)

#: Long enough that nothing in this file is decided by the deadline unless it
#: says so. `TestOneDeadlineForTheWholePhase` sets its own.
ROOMY_SECONDS = 3600


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
    on attempt three as on attempt one - or, for the timeout, deliberately not.

    An attempt also TAKES time. With `takes_seconds` set it spends that much of
    `clock`, capped at whatever timeout it was granted, which is what a real
    attempt does: the harness is killed at its deadline rather than running
    past it.
    """

    scripted: FakeAgentExecutionHandler
    clock: FakeClock | None = None
    takes_seconds: float = 0.0
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
        if self.clock is not None and self.takes_seconds:
            self.clock.advance(min(self.takes_seconds, float(timeout_seconds)))
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


def _phase(
    provider: str = AgentProvider.CLAUDE, timeout_seconds: int = ROOMY_SECONDS
) -> ExecutablePhase:
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
    retry_policy: UpstreamRetryPolicy = NO_WAITING,
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
        retry_policy=retry_policy,
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
        """Same session, same container. A retry that re-resolved either would
        be a different run wearing the same phase id.

        The BUDGET is the deliberate exception and has its own class below: it
        is the one thing a retry must not get a fresh copy of.
        """
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


class TestOneDeadlineForTheWholePhase:
    """A phase's configured timeout bounds the WHOLE sequence, not each attempt.

    Every attempt used to be handed `phase.timeout_seconds` again, so the bound
    a phase was configured with was really three times that plus the backoff: a
    3600-second phase could occupy a worker for 10,815 seconds and bill three
    phases' tokens doing it. Nothing in the result said so, because the caller
    receives one result either way.
    """

    async def test_an_attempt_is_given_what_is_left_of_the_phase(self) -> None:
        """Strictly less each time, and by what the last attempt actually spent.

        This is the assertion that fails against a per-attempt timeout, and it
        fails loudly: identical numbers instead of descending ones.
        """
        clock = FakeClock()
        handler = _RecordingHandler(
            clock=clock,
            takes_seconds=600.0,
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            ),
        )

        await _run(
            handler,
            phase=_phase(timeout_seconds=3600),
            retry_policy=UpstreamRetryPolicy(clock=clock.as_attempt_clock()),
        )

        granted = [a.timeout_seconds for a in handler.attempts]
        assert granted == [3600, 2995, 2385], (
            f"{granted}: each attempt must get the phase's REMAINING seconds - "
            "its own 600s and the 5s/10s backoff already deducted"
        )

    async def test_the_whole_sequence_fits_inside_the_configured_timeout(self) -> None:
        """Attempts plus backoff, against the number an operator configured.

        The handler here wants more time than the phase has, so it is cut off
        at whatever it was granted - which is what a real harness killed at its
        deadline does. Under a per-attempt timeout this same run spends 7205
        seconds on a 3600-second phase.
        """
        clock = FakeClock()
        handler = _RecordingHandler(
            clock=clock,
            takes_seconds=1_000_000.0,
            scripted=FakeAgentExecutionHandler(
                attempts=[FakeAgentExecutionHandler.failed(reason=AT_CAPACITY)]
            ),
        )

        await _run(
            handler,
            phase=_phase(timeout_seconds=3600),
            retry_policy=UpstreamRetryPolicy(clock=clock.as_attempt_clock()),
        )

        assert clock.now <= 3600.0, (
            f"{clock.now}s spent on a 3600s phase across "
            f"{len(handler.attempts)} attempts and {clock.slept} of backoff"
        )

    async def test_a_deadline_with_no_room_left_ends_the_retrying(self) -> None:
        """Attempts remain and the upstream is still busy - and it stops anyway.

        `max_attempts` is 3 and only two are spent. What stopped it is the
        clock: the first attempt used nearly the whole phase, so a third would
        have been launched into a budget too small to start a container in.
        """
        clock = FakeClock()
        handler = _RecordingHandler(
            clock=clock,
            takes_seconds=590.0,
            scripted=FakeAgentExecutionHandler(
                attempts=[FakeAgentExecutionHandler.failed(reason=AT_CAPACITY)]
            ),
        )

        await _run(
            handler,
            phase=_phase(timeout_seconds=600),
            retry_policy=UpstreamRetryPolicy(clock=clock.as_attempt_clock()),
        )

        assert len(handler.attempts) == 1, (
            f"{len(handler.attempts)} attempts: a second was launched with "
            f"{600 - clock.now}s of budget left to run it in"
        )
        assert clock.slept == [], "waited out a backoff for an attempt it could not afford"


class TestOnlyALaunchThatNeverStartedIsRetried:
    """A retry re-runs the ORIGINAL prompt against the SAME workspace.

    That is idempotent exactly while the attempt it replaces did nothing. An
    agent that had already edited a file, run a command or pushed a branch
    would do it again from a tree that is no longer the one the prompt was
    written against - and the busy upstream says nothing about whether that
    happened, so the attempt's own record has to.
    """

    async def test_a_busy_upstream_before_any_work_is_retried(self) -> None:
        """The control for the whole class, and the case #1303 is about.

        Without it, every assertion below passes just as well on a change that
        retries nothing at all.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        result = await _run(handler)

        assert len(handler.attempts) == 2
        assert result.command.exit_code == 0

    async def test_a_busy_upstream_after_a_tool_call_is_not_retried(self) -> None:
        """The same reason, the same budget, the same everything but one tool
        call - and it fails, exactly as it did before any of this existed.

        The tool ran against the workspace. Re-running the prompt would run it
        a second time, from a tree it has already changed, and a `git push` or
        a `gh pr create` does not come back the same way twice.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY, uses_tools=["Bash"]),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        result = await _run(handler)

        assert len(handler.attempts) == 1, (
            "An attempt that had already run a tool was re-run from the top."
        )
        assert result.command.exit_code == 1
        assert result.stream_result.error_reason == AT_CAPACITY, (
            "and it fails with the upstream's own reason, unchanged"
        )

    async def test_a_busy_upstream_after_the_agent_spoke_is_not_retried(self) -> None:
        """An assistant turn is work too, even when it called nothing.

        The agent got far enough to answer. A rerun pays for that turn twice
        and throws the first one away, which is the cost this whole module
        exists to avoid paying.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY, says="Working on it."),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        result = await _run(handler)

        assert len(handler.attempts) == 1
        assert result.command.exit_code == 1

    async def test_work_on_an_earlier_attempt_stops_the_later_ones(self) -> None:
        """The rule is about the PHASE, not the attempt in hand.

        Attempt one starts nothing and is retried. Attempt two runs a tool and
        fails busy. Attempt three would be a rerun over attempt two's changes,
        so the bound of 3 is never reached.
        """
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY, uses_tools=["Edit"]),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        result = await _run(handler)

        assert len(handler.attempts) == 2, (
            f"{len(handler.attempts)} attempts: attempt 2 changed the workspace "
            "and attempt 3 re-ran the prompt over it anyway"
        )
        assert result.command.exit_code == 1


class TestNothingIsDispatchedOnAnExpiredDeadline:
    """What the handler is actually CALLED with, once the backoff overslept.

    `test_busy_upstream.py` pins the decision; this pins the dispatch, and they
    are not the same hop. The decision said "go again" and the caller then read
    `seconds_left` for itself and truncated it, so a deadline that expired
    during the wait produced `timeout_seconds=0` - which the workspace provider
    reads as NO timeout (`if not timeout_seconds: return False`), making the
    attempt that should not have run at all the one attempt with no bound.
    """

    async def test_a_backoff_that_overshoots_the_deadline_launches_nothing(self) -> None:
        clock = FakeClock(oversleeps_by=45.0)
        handler = _RecordingHandler(
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            )
        )

        await _run(
            handler,
            phase=_phase(timeout_seconds=40),
            retry_policy=UpstreamRetryPolicy(clock=clock.as_attempt_clock()),
        )

        assert len(handler.attempts) == 1, (
            f"the wait came back {clock.now - 40:.0f}s past a 40s deadline and a "
            "successor was dispatched anyway"
        )

    async def test_an_overshoot_past_an_hour_long_phase_launches_nothing(self) -> None:
        """The same, at the largest timeout the platform configures, and with
        an attempt that really spent the budget rather than a deadline set
        short enough to expire on its own."""
        clock = FakeClock(oversleeps_by=3600.0)
        handler = _RecordingHandler(
            clock=clock,
            takes_seconds=3565.0,
            scripted=FakeAgentExecutionHandler(
                attempts=[
                    FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
                    FakeAgentExecutionHandler.success(),
                ]
            ),
        )

        await _run(
            handler,
            phase=_phase(timeout_seconds=3600),
            retry_policy=UpstreamRetryPolicy(clock=clock.as_attempt_clock()),
        )

        assert len(handler.attempts) == 1
        assert clock.now > 3600.0, "the clock never overshot - the test proves nothing"

    @pytest.mark.parametrize("oversleeps_by", [0.0, 0.5, 30.0, 45.0, 3600.0])
    async def test_no_attempt_is_ever_given_a_timeout_of_zero(self, oversleeps_by: float) -> None:
        """Across every overshoot the cases above single out, and the honest
        clock alongside them.

        Zero is not a short timeout downstream, it is an unbounded one, so this
        is the invariant rather than an assertion about any one path: whatever
        the clock did, every number this module hands a handler still MEANS a
        limit.
        """
        clock = FakeClock(oversleeps_by=oversleeps_by)
        handler = _RecordingHandler(
            clock=clock,
            takes_seconds=25.0,
            scripted=FakeAgentExecutionHandler(
                attempts=[FakeAgentExecutionHandler.failed(reason=AT_CAPACITY)]
            ),
        )

        await _run(
            handler,
            phase=_phase(timeout_seconds=70),
            retry_policy=UpstreamRetryPolicy(clock=clock.as_attempt_clock()),
        )

        granted = [a.timeout_seconds for a in handler.attempts]
        assert granted, "nothing was dispatched at all - the invariant is vacuous"
        assert all(t > 0 for t in granted), (
            f"{granted}: a handler was given a falsey timeout, which the workspace "
            "provider reads as no timeout at all"
        )
