"""PC-83 through the REAL stream parsers: raw harness JSONL decides the fallback.

`test_pc83_a_phase_falls_back_once.py` scripts each attempt's outcome as a
post-parser string, so it proves the fallback rule is applied and can never
prove the parsers classify a real busy or quota line as the failure kinds that
rule accepts. Here every attempt is RAW JSONL, read by `EventStreamProcessor`
or `CodexStreamProcessor` - whichever the runner `run_phase_agent` picked for
that attempt says - under `processor.run()` with the real provisioning
handler. What is asserted is the recorded `AgentExecutionCompleted`, the
execution detail the API reads, and the message an operator sees.

Mutation check: replacing the fallback dispatch in `run_phase_agent` with a
return of the primary's result fails (a) and (b) below.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration import (
    AgentExecutionCompletedCommand,
    AgentExecutionResult,
    SubagentTracker,
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE
from syn_shared.agents import AgentProvider, AgentRunner

from .test_processor_smoke import FakeExecutionRepository, _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from event_sourcing import DomainEvent

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
        PhaseCostLimit,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)

SUCCEEDED = 'TASK_RESULT: {"success": true, "comments": "verified"}\nTASK_RESULT_END'

#: Claude's busy fault as the raw terminal line claude writes (#1303).
CLAUDE_OVERLOADED = json.dumps(
    {
        "type": "result",
        "is_error": True,
        "result": (
            'API Error: 529 {"type":"error","error":'
            '{"type":"overloaded_error","message":"Overloaded"}}'
        ),
    }
)

#: The real codex quota sentence, observed 2026-10-06, on the event codex puts it on.
CODEX_QUOTA_SENTENCE = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
    "purchase more credits or try again at Oct 9th, 2026 9:10 PM."
)
CODEX_QUOTA = json.dumps({"type": "turn.failed", "error": {"message": CODEX_QUOTA_SENTENCE}})

#: A failure that is neither busy nor quota, for the fallback itself to hit.
CODEX_NOT_LOGGED_IN = json.dumps(
    {
        "type": "turn.failed",
        "error": {"message": "You are not logged in. Run `codex login` to continue."},
    }
)

CLAUDE_SUCCEEDS = json.dumps({"type": "result", "is_error": False, "result": SUCCEEDED})
CODEX_SUCCEEDS = (
    json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": SUCCEEDED}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
)

CODEX_FALLBACK = AgentConfiguration(provider=AgentProvider.CODEX, model="gpt-5.1-codex-max")
CLAUDE_FALLBACK = AgentConfiguration(provider=AgentProvider.CLAUDE, model="claude-fallback-model")


async def _as_stream(lines: tuple[str, ...]) -> AsyncIterator[str]:
    for line in lines:
        yield line


@dataclass
class _RawJsonlAgent:
    """Feeds each attempt's raw lines to production's parser for that attempt's runner.

    The double decides nothing about what a stream meant: the parser's
    `StreamResult` is what `run_phase_agent` judges. A clean stream writes the
    deliverable, as an agent that finished would have.
    """

    attempts: tuple[tuple[str, ...], ...]
    runners: list[Runner] = field(default_factory=list)

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
        cost_limit: PhaseCostLimit | None = None,
    ) -> AgentExecutionResult:
        self.runners.append(runner)
        lines = self.attempts[len(self.runners) - 1]
        assert todo.phase_id is not None
        if on_launch is not None:
            await on_launch()
        tokens = TokenAccumulator()
        subagents = SubagentTracker()
        parser: EventStreamProcessor | CodexStreamProcessor
        if runner == AgentRunner.CODEX:
            parser = CodexStreamProcessor(
                tokens=tokens,
                collector=collector,
                controller=None,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                agent_model=agent_model,
                rollout=None,
            )
        else:
            parser = EventStreamProcessor(
                tokens=tokens,
                subagents=subagents,
                observability=None,
                controller=None,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                workspace_id=None,
                agent_model=agent_model,
                collector=collector,
            )
        stream_result = await parser.process_stream(_as_stream(lines), workspace)
        if not stream_result.error_reason:
            await workspace.inject_files(list(A_DELIVERABLE))
        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=AgentExecutionCompletedCommand(
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                exit_code=1 if stream_result.error_reason else 0,
                last_agent_message=stream_result.last_agent_message,
            ),
        )


# pyright verifies the double still matches the real handler's contract.
_: AgentHandlerProtocol = _RawJsonlAgent(attempts=())


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
    agent: _RawJsonlAgent, phase: ExecutablePhase, execution_id: str
) -> tuple[WorkflowExecutionResult, _RecordingRepository]:
    repository = _RecordingRepository()
    processor = _make_processor(agent, retry_policy=NO_WAITING, execution_repository=repository)
    result = await processor.run(
        workflow_id="wf-pc83-raw",
        workflow_name="Fallback agent, raw streams",
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


class TestRawStreamsFallBack:
    async def test_a_claude_overloaded_past_its_retries_completes_on_the_fallback(self) -> None:
        """(a) Raw claude 529 on every retry, then the codex fallback finishes the phase."""
        agent = _RawJsonlAgent(
            attempts=(*[(CLAUDE_OVERLOADED,)] * NO_WAITING.max_attempts, CODEX_SUCCEEDS)
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CLAUDE), CODEX_FALLBACK)

        result, repository = await _run(agent, phase, "exec-pc83-raw-capacity")

        assert result.status == "completed", result.error_message
        assert agent.runners == [AgentRunner.CLAUDE] * NO_WAITING.max_attempts + [AgentRunner.CODEX]
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CODEX
        assert completed.agent_model == "gpt-5.1-codex-max"
        (row,) = (await _detail(repository, "exec-pc83-raw-capacity")).phases
        assert row.agent_provider == AgentProvider.CODEX
        assert row.agent_model == "gpt-5.1-codex-max"

    async def test_b_a_codex_quota_is_not_retried_and_completes_on_the_fallback(self) -> None:
        """(b) Raw codex quota: one primary attempt, no retry, then the claude fallback."""
        agent = _RawJsonlAgent(attempts=((CODEX_QUOTA,), (CLAUDE_SUCCEEDS,)))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-pc83-raw-quota")

        assert result.status == "completed", result.error_message
        assert agent.runners == [AgentRunner.CODEX, AgentRunner.CLAUDE], (
            "a spent quota was retried on the primary, or the fallback never ran"
        )
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CLAUDE
        assert completed.agent_model == "claude-fallback-model"

    async def test_c_a_codex_quota_with_no_fallback_fails_fast_with_its_reset_time(self) -> None:
        """(c) No fallback declared: one attempt, and the error names the reset time."""
        agent = _RawJsonlAgent(attempts=((CODEX_QUOTA,), (CODEX_SUCCEEDS)))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), None)

        result, _repository = await _run(agent, phase, "exec-pc83-raw-quota-alone")

        assert result.status == "failed"
        assert agent.runners == [AgentRunner.CODEX], "a spent quota was retried"
        assert result.error_message is not None
        assert "codex quota exhausted until 2026-10-09T21:10" in result.error_message, (
            result.error_message
        )

    async def test_d_a_failing_fallback_fails_the_phase_naming_both_failures(self) -> None:
        """(d) Claude busy past its retries, then the codex fallback fails on its own."""
        agent = _RawJsonlAgent(
            attempts=(*[(CLAUDE_OVERLOADED,)] * NO_WAITING.max_attempts, (CODEX_NOT_LOGGED_IN,))
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CLAUDE), CODEX_FALLBACK)

        result, _repository = await _run(agent, phase, "exec-pc83-raw-both-fail")

        assert result.status == "failed"
        assert agent.runners[-1] == AgentRunner.CODEX
        message = result.error_message or ""
        assert "overloaded" in message.lower(), message
        assert "Then the fallback agent failed" in message, message
        assert "not logged in" in message, message
