"""PC-83: a phase whose provider cannot serve it runs ONCE on its declared fallback.

Driven through `processor.run()` with the real provisioning handler, so the
fallback's command and env are built by the same code that builds the
primary's, and the recorded `AgentExecutionCompleted` event is read back from
the repository. What is asserted is the RECORDED outcome: which agent the
event says produced the result, what the run ended as, how many times the
agent was asked and on which runner, and the message an operator reads.

Mutation check: deleting the fallback dispatch in `run_phase_agent` (the
`run.once(...)` call and what follows it, returning `primary.result`) fails
`test_capacity_past_its_retries_runs_the_fallback` and
`test_a_spent_quota_is_not_retried_and_runs_the_fallback`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler
from syn_shared.agents import AgentProvider, AgentRunner
from syn_shared.upstream_failure import UpstreamFailureKind

from .test_processor_smoke import FakeExecutionRepository, _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

#: Claude's capacity fault, as the claude stream processor spells it.
OVERLOADED = "API overloaded (HTTP 529)"

#: The real codex quota line, observed 2026-10-06, as codex's processor wraps it.
CODEX_QUOTA = codex_fault_reason(
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
    "purchase more credits or try again at Oct 9th, 2026 9:10 PM."
)

#: A failure a fallback must not paper over, and one the fallback itself hits.
NOT_LOGGED_IN = codex_fault_reason("You are not logged in. Run `codex login` to continue.")

SUCCEEDED = 'TASK_RESULT: {"success": true, "comments": "verified"}\nTASK_RESULT_END'

NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)

#: Models no default resolves to, so a recorded one can only have come from
#: the fallback declaration.
CODEX_FALLBACK = AgentConfiguration(provider=AgentProvider.CODEX, model="gpt-5.1-codex-max")
CLAUDE_FALLBACK = AgentConfiguration(provider=AgentProvider.CLAUDE, model="claude-fallback-model")


class _RecordingRepository(FakeExecutionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[DomainEvent] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(envelope.event for envelope in aggregate.get_uncommitted_events())
        await super().save(aggregate)


def _phase(primary: AgentConfiguration, fallback: AgentConfiguration | None) -> ExecutablePhase:
    (phase,) = _one_phase_workflow()
    return replace(phase, agent_config=primary, fallback_agent=fallback)


async def _run(
    fake: FakeAgentExecutionHandler, phase: ExecutablePhase, execution_id: str
) -> tuple[WorkflowExecutionResult, _RecordingRepository]:
    repository = _RecordingRepository()
    processor = _make_processor(fake, retry_policy=NO_WAITING, execution_repository=repository)
    result = await processor.run(
        workflow_id="wf-pc83",
        workflow_name="Fallback agent",
        phases=[phase],
        inputs={},
        execution_id=execution_id,
    )
    return result, repository


def _completed(repository: _RecordingRepository) -> AgentExecutionCompletedEvent:
    (event,) = [e for e in repository.events if isinstance(e, AgentExecutionCompletedEvent)]
    return event


async def _detail(repository: _RecordingRepository, execution_id: str) -> WorkflowExecutionDetail:
    """The execution record GET /executions/{id} serves, built from the run's own events."""
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for event in repository.events:
        handler_name = ExecutionJournal._event_type_to_handler(  # pyright: ignore[reportPrivateUsage]
            getattr(event, "event_type", type(event).__name__)
        )
        handler = getattr(projection, handler_name, None)
        if handler:
            await handler(ExecutionJournal._serialize_event(event))  # pyright: ignore[reportPrivateUsage]
    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, execution_id)
    assert record is not None
    return WorkflowExecutionDetail.from_dict(record)


class TestTheExecutionShowsTheAgentThatRan:
    async def test_the_detail_names_the_fallback_after_a_fallback(self) -> None:
        """The phase row an operator opens names the fallback, not the declared agent."""
        fake = FakeAgentExecutionHandler.scripted(
            *[FakeAgentExecutionHandler.failed(stream_error=OVERLOADED)] * NO_WAITING.max_attempts,
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CLAUDE), CODEX_FALLBACK)

        result, repository = await _run(fake, phase, "exec-pc83-detail")

        assert result.status == "completed", result.error_message
        (row,) = (await _detail(repository, "exec-pc83-detail")).phases
        assert row.agent_provider == AgentProvider.CODEX
        assert row.agent_model == "gpt-5.1-codex-max"

    async def test_a_phase_recorded_before_pc83_names_no_agent(self) -> None:
        """An event without the fields leaves the row's agent unknown, never a guess."""
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )
        result, repository = await _run(fake, _phase(AgentConfiguration(), None), "exec-pc83-old")
        assert result.status == "completed", result.error_message
        repository.events = [
            e.model_copy(update={"agent_provider": None, "agent_model": None})
            if isinstance(e, AgentExecutionCompletedEvent)
            else e
            for e in repository.events
        ]

        (row,) = (await _detail(repository, "exec-pc83-old")).phases
        assert row.agent_provider is None
        assert row.agent_model is None


class TestTheFallbackRuns:
    async def test_capacity_past_its_retries_runs_the_fallback(self) -> None:
        """(a) Busy for every retry, then the fallback answers and the phase completes."""
        fake = FakeAgentExecutionHandler.scripted(
            *[FakeAgentExecutionHandler.failed(stream_error=OVERLOADED)] * NO_WAITING.max_attempts,
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CLAUDE), CODEX_FALLBACK)

        result, repository = await _run(fake, phase, "exec-pc83-capacity")

        assert result.status == "completed", result.error_message
        assert fake.call_count == NO_WAITING.max_attempts + 1
        assert fake.runners[: NO_WAITING.max_attempts] == [AgentRunner.CLAUDE] * 3
        assert fake.runners[-1] == AgentRunner.CODEX, "the fallback ran on the primary's parser"
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CODEX
        assert completed.agent_model == "gpt-5.1-codex-max"

    async def test_a_spent_quota_is_not_retried_and_runs_the_fallback(self) -> None:
        """(b) Quota: one attempt on the primary, never retried, then the fallback."""
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error=CODEX_QUOTA),
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(fake, phase, "exec-pc83-quota")

        assert result.status == "completed", result.error_message
        assert fake.call_count == 2, "a spent quota was retried on the primary"
        assert fake.runners == [AgentRunner.CODEX, AgentRunner.CLAUDE]
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CLAUDE
        assert completed.agent_model == "claude-fallback-model"

    async def test_the_primary_that_succeeds_is_recorded_as_itself(self) -> None:
        """The control: no fallback run, and the event names the declared agent."""
        fake = FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED)
        primary = AgentConfiguration(provider=AgentProvider.CLAUDE, model="claude-primary-model")

        _result, repository = await _run(fake, _phase(primary, CODEX_FALLBACK), "exec-pc83-ok")

        assert fake.call_count == 1
        completed = _completed(repository)
        assert (completed.agent_provider, completed.agent_model) == (
            AgentProvider.CLAUDE,
            "claude-primary-model",
        )

    async def test_a_genuine_error_does_not_run_the_fallback(self) -> None:
        """Only CAPACITY and QUOTA hand over: a bad login is the phase's answer."""
        fake = FakeAgentExecutionHandler.failed(stream_error=NOT_LOGGED_IN)
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, _ = await _run(fake, phase, "exec-pc83-auth")

        assert result.status == "failed"
        assert fake.call_count == 1


class TestWhenItCannotHelp:
    async def test_a_spent_quota_with_no_fallback_fails_fast_with_its_reset(self) -> None:
        """(c) No fallback declared: one attempt, and the error says until when."""
        fake = FakeAgentExecutionHandler.failed(stream_error=CODEX_QUOTA)
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), None)

        result, repository = await _run(fake, phase, "exec-pc83-no-fallback")

        assert result.status == "failed"
        assert fake.call_count == 1, "a spent quota was retried"
        assert result.error_message is not None
        assert "codex quota exhausted until 2026-10-09T21:10" in result.error_message
        (failed,) = [e for e in repository.events if isinstance(e, WorkflowFailedEvent)]
        assert failed.upstream_failure_kind is UpstreamFailureKind.QUOTA

    async def test_a_fallback_that_fails_too_reports_both_failures(self) -> None:
        """(d) The fallback is run once, not retried, and both causes reach the operator."""
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error=CODEX_QUOTA),
            FakeAgentExecutionHandler.failed(stream_error=OVERLOADED),
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, _ = await _run(fake, phase, "exec-pc83-both-fail")

        assert result.status == "failed"
        assert fake.call_count == 2, "the fallback was retried, or never ran"
        message = result.error_message
        assert message is not None
        assert "codex quota exhausted until 2026-10-09T21:10" in message, message
        assert "You've hit your usage limit" in message, message
        assert "API overloaded (HTTP 529)" in message, message
