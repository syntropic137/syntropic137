"""A phase that loses only its terminal usage event costs one phase, not the run.

THE INCIDENT (#1335). A codex `verify` phase ended without a `turn.completed`
event. That event carries the run's authoritative usage, so the phase correctly
refused to complete - completing on unknown usage would write a number into
cost attribution that means something else. But the refusal failed the whole
EXECUTION, discarding a `premise` and an `implement` phase that had already run,
already pushed their branch, and already been paid for. Three runs and $25.15 in
one day.

WHAT THESE TESTS PIN, and the reason they drive `processor.run()` rather than
any one of the pieces. The fix spans four hops that each pass their own
neighbours' tests while the whole is broken:

  1. the processor decides to retry instead of raising,
  2. the aggregate grants the attempt and records that it did,
  3. the to-do projection puts the phase back on the list - which means SETTING
     its monotonic highwater rank back, because merging it (the rule every
     other handler follows) silently filters the new item out at `get_pending`
     and the retry goes missing with nothing anywhere saying so,
  4. `record_agent_run` sums the attempts' token counts instead of overwriting.

A test at any single hop is green with hop 3 or hop 4 broken. Only "the
execution completed AND the phase ran exactly twice AND it reports what both
attempts spent" sees all four.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    PhaseUsage,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    MAX_PHASE_ATTEMPTS,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
    )

from syn_shared.agents import AgentRunner


class AttemptSequence:
    """An agent that answers ONE named phase differently on each attempt at it.

    Every other double in this suite answers the same way however many times it
    is asked, which is exactly the property a retry cannot be tested against: a
    phase that fails once and then works is the shape the fix exists for, and
    one that fails identically forever is the shape the budget exists for. The
    last entry answers every attempt after it, so both are one sentence.

    Scoped to a phase because the loss being pinned is what a LATE phase's
    failure does to an EARLY phase's result; every phase other than the named
    one simply succeeds, so any re-run of one is the test failing rather than
    the double being clever.
    """

    def __init__(self, phase_id: str, *attempts: FakeAgentExecutionHandler) -> None:
        self._phase_id = phase_id
        self._attempts = attempts
        self._every_other_phase = FakeAgentExecutionHandler.success()
        self.calls: list[TodoItem] = []

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
        attempts_so_far = self.attempts_at(todo.phase_id or "")
        self.calls.append(todo)
        if todo.phase_id != self._phase_id:
            handler = self._every_other_phase
        else:
            handler = self._attempts[min(attempts_so_far, len(self._attempts) - 1)]
        return await handler.handle(
            todo=todo,
            workspace=workspace,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            session_id=session_id,
            agent_model=agent_model,
            timeout_seconds=timeout_seconds,
            collector=collector,
            runner=runner,
            on_launch=on_launch,
        )

    def attempts_at(self, phase_id: str) -> int:
        """How many times this phase was handed to an agent."""
        return sum(1 for call in self.calls if call.phase_id == phase_id)


_: AgentHandlerProtocol = AttemptSequence("phase")


def _lost_its_terminal_event(spent: PhaseUsage | None = None) -> FakeAgentExecutionHandler:
    """The #1335 fault verbatim: non-zero exit, and the one reason that is not a fault.

    `exit_code=1` with this reason is what `AgentExecutionHandler` produces for
    a codex stream that stopped early and left NO deliverable behind - a verify
    phase, which authors nothing, so #1111's deliverable salvage can never
    reach it.
    """
    return FakeAgentExecutionHandler.failed(
        exit_code=1,
        stream_error=MISSING_TERMINAL_TURN_REASON,
        spent=spent,
    )


def _implement_then_verify() -> list[ExecutablePhase]:
    """The two phases whose relationship the incident is about.

    `implement` authors, pushes and is paid for; `verify` authors nothing and
    certifies. Two rather than one because the loss being pinned is what
    happens to the FIRST when the second refuses.
    """
    return [
        ExecutablePhase(
            phase_id="implement",
            name="Implement",
            order=1,
            agent_config=AgentConfiguration(provider="codex"),
            prompt_template="make the change",
            output_artifact_types=(),
            timeout_seconds=30,
        ),
        ExecutablePhase(
            phase_id="verify",
            name="Verify",
            order=2,
            agent_config=AgentConfiguration(provider="codex"),
            prompt_template="certify the change",
            output_artifact_types=(),
            timeout_seconds=30,
        ),
    ]


@pytest.mark.unit
class TestALostTerminalEventIsRetriedInPlace:
    """The response to the fault changes; the refusal itself does not."""

    async def test_the_run_survives_and_only_the_verify_phase_is_repeated(self) -> None:
        """The headline: one bad attempt costs one attempt, not the run.

        `implement` ran once and kept its result - that is the $8 the incident
        was about. `verify` ran twice, in the same execution, off the same
        to-do list, against the same inputs and the same repositories at the
        same commits, because nothing about the execution changed.
        """
        agent = AttemptSequence(
            "verify",
            _lost_its_terminal_event(),
            FakeAgentExecutionHandler.success(),
        )
        processor = _make_processor(agent)  # type: ignore[arg-type]

        result = await processor.run(
            workflow_id="wf-1335",
            workflow_name="Implement then verify",
            phases=_implement_then_verify(),
            inputs={},
            execution_id="exec-1335-retried",
        )

        assert result.status == "completed", (
            f"Expected 'completed' but got '{result.status}'. A verify phase that "
            "lost only its terminal usage event took the whole execution down "
            "with it, discarding the implement phase that had already run (#1335)."
        )
        assert agent.attempts_at("implement") == 1, (
            "The implement phase was re-run. A retry must be scoped to the phase "
            "that failed; re-running an earlier phase is the cost the fix exists "
            "to avoid."
        )
        assert agent.attempts_at("verify") == MAX_PHASE_ATTEMPTS, (
            f"Expected the verify phase to be attempted {MAX_PHASE_ATTEMPTS} times, "
            f"got {agent.attempts_at('verify')}. One attempt means the retry never "
            "reached the to-do list - most likely the projection MERGED the phase's "
            "highwater rank instead of setting it, so get_pending filtered the new "
            "item out as stale."
        )
        assert {r.phase_id for r in result.phase_results} == {"implement", "verify"}

    async def test_the_phase_reports_what_BOTH_its_attempts_spent(self) -> None:
        """A phase that ran twice cost both runs, and says so.

        The hop under test is `record_agent_run`, which is called once per
        attempt and used to ASSIGN the phase's token counts. Assigning reports
        the retry's spend as the phase's and leaves the dead attempt's money
        recorded nowhere the phase's own report can see - which is the same
        disease the refusal exists to prevent, arriving by the other door.

        The two attempts spend DIFFERENT amounts, so neither a sum reported as
        one attempt's nor one attempt's reported as the sum can pass.
        """
        agent = AttemptSequence(
            "verify",
            _lost_its_terminal_event(spent=PhaseUsage(input_tokens=700, output_tokens=90)),
            FakeAgentExecutionHandler.success(
                spent=PhaseUsage(input_tokens=1300, output_tokens=210)
            ),
        )
        processor = _make_processor(agent)  # type: ignore[arg-type]

        result = await processor.run(
            workflow_id="wf-1335",
            workflow_name="Implement then verify",
            phases=_implement_then_verify(),
            inputs={},
            execution_id="exec-1335-spend",
        )

        assert result.status == "completed"
        verify = next(r for r in result.phase_results if r.phase_id == "verify")
        assert (verify.input_tokens, verify.output_tokens) == (2000, 300), (
            f"Expected the two attempts summed (2000, 300) but got "
            f"({verify.input_tokens}, {verify.output_tokens}). "
            "(1300, 210) means the dead attempt's spend was overwritten; "
            "(700, 90) means the retry's was dropped."
        )

    async def test_a_fault_that_recurs_fails_the_run_after_its_budget(self) -> None:
        """The budget is a ceiling on the bill, not an invitation to loop.

        The fault is indistinguishable from the outside from one that will
        happen every time, so every attempt past the first is money spent on a
        guess. When the guess is wrong the execution fails exactly as it did
        before the fix - one phase's budget later, not none and not forever.
        """
        agent = AttemptSequence("verify", _lost_its_terminal_event())
        processor = _make_processor(agent)  # type: ignore[arg-type]

        result = await processor.run(
            workflow_id="wf-1335",
            workflow_name="Implement then verify",
            phases=_implement_then_verify(),
            inputs={},
            execution_id="exec-1335-exhausted",
        )

        assert result.status == "failed"
        assert agent.attempts_at("verify") == MAX_PHASE_ATTEMPTS, (
            f"Expected exactly {MAX_PHASE_ATTEMPTS} attempts, got "
            f"{agent.attempts_at('verify')}. More than that means the budget is "
            "not being counted from the event stream and a phase can bill "
            "indefinitely."
        )

    async def test_a_failure_that_names_a_real_fault_is_not_retried(self) -> None:
        """Only the reason that names NO fault earns another attempt.

        A login that is not valid, a line that does not parse, a non-zero exit
        with no reason at all: a second attempt hits the same wall and bills
        for it. The narrowness is the whole safety of the fix, so it is pinned
        rather than left to the reader of the condition.
        """
        agent = AttemptSequence(
            "verify",
            FakeAgentExecutionHandler.failed(
                exit_code=1, stream_error="codex login failed: refresh_token_reused"
            ),
            FakeAgentExecutionHandler.success(),
        )
        processor = _make_processor(agent)  # type: ignore[arg-type]

        result = await processor.run(
            workflow_id="wf-1335",
            workflow_name="Implement then verify",
            phases=_implement_then_verify(),
            inputs={},
            execution_id="exec-1335-real-fault",
        )

        assert result.status == "failed"
        assert agent.attempts_at("verify") == 1, (
            "A phase that failed for a reason naming a real fault was retried. "
            "The retry is for the one reason that names no fault of the run's "
            "own; widening it spends the phase's budget again on a wall that "
            "has not moved."
        )
