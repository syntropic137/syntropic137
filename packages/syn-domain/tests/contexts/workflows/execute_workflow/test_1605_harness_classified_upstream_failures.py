"""#1605: what an upstream fault asks of a phase is read off agentic-workspace's classifiers.

Driven through `processor.run()`, so each recorded reason travels the whole
production path: the reader bound at `UPSTREAM_FAILURES`, the retry and
fallback rule in `busy_upstream`, the error text `agent_run_outcome` builds,
and the `WorkflowFailed` event the execution records. What is asserted is
what an operator sees: how many times the agent ran, the execution's error,
and the kind the failure was recorded under.

The two claude sentences are the weekly-limit lines #1605 records
(exec-8ad0e101db7b; PC-234's exec-b933b563fd25 and exec-366b5b8ea00d read as
`unknown` before this). The codex sentence is #1303's.

Mutations (`.mutations/1605-*.patch`), and the test that kills each:

- QUOTA made transient: `test_a_claude_weekly_limit_is_not_retried_and_says_when_it_resets`
- `resets_at` dropped from the quota: the same test (the error says "an unstated time")
- QUOTA mapped to UNKNOWN by a default branch:
  `test_a_claude_weekly_limit_runs_the_fallback` and the same test (the recorded kind)
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.upstream_failure import (
    HarnessUpstreamFailureReader,
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

#: Claude's weekly-limit lines, as the CLI's error result carries them. Claude
#: prints no year, so a reset is asserted by its month, day and hour: the year
#: is placed by when the reason is read (see `test_the_year_is_placed_by_the_reading`).
CLAUDE_WEEKLY_LIMITS = {
    "resets Oct 15, 8am": (
        "You've hit your weekly limit · resets Oct 15, 8am (UTC)",
        r"claude quota exhausted until \d{4}-10-15T08:00:00\+00:00",
    ),
    "resets Oct 23, 3pm": (
        "You've hit your weekly limit · resets Oct 23, 3pm (UTC)",
        r"claude quota exhausted until \d{4}-10-23T15:00:00\+00:00",
    ),
}

#: Codex's capacity sentence (#1303), as codex's processor wraps it.
CODEX_AT_CAPACITY = codex_fault_reason(
    "Selected model is at capacity. Please try a different model."
)

SUCCEEDED = 'TASK_RESULT: {"success": true, "comments": "verified"}\nTASK_RESULT_END'

NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)

CLAUDE = AgentConfiguration(provider=AgentProvider.CLAUDE)
CODEX = AgentConfiguration(provider=AgentProvider.CODEX)
CODEX_FALLBACK = AgentConfiguration(provider=AgentProvider.CODEX, model="gpt-5.1-codex-max")


class _RecordingRepository(FakeExecutionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[DomainEvent] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(envelope.event for envelope in aggregate.get_uncommitted_events())
        await super().save(aggregate)


async def _run(
    fake: FakeAgentExecutionHandler,
    primary: AgentConfiguration,
    fallback: AgentConfiguration | None = None,
) -> tuple[WorkflowExecutionResult, _RecordingRepository]:
    (phase,) = _one_phase_workflow()
    phase: ExecutablePhase = replace(phase, agent_config=primary, fallback_agent=fallback)
    repository = _RecordingRepository()
    processor = _make_processor(fake, retry_policy=NO_WAITING, execution_repository=repository)
    result = await processor.run(
        workflow_id="wf-1605",
        workflow_name="Upstream failures",
        phases=[phase],
        inputs={},
        execution_id="exec-1605",
    )
    return result, repository


def _failed_kind(repository: _RecordingRepository) -> UpstreamFailureKind | None:
    (failed,) = [e for e in repository.events if isinstance(e, WorkflowFailedEvent)]
    return failed.upstream_failure_kind


class TestAClaudeWeeklyLimit:
    @pytest.mark.parametrize(
        ("reason", "surfaced"), CLAUDE_WEEKLY_LIMITS.values(), ids=CLAUDE_WEEKLY_LIMITS
    )
    async def test_a_claude_weekly_limit_is_not_retried_and_says_when_it_resets(
        self, reason: str, surfaced: str
    ) -> None:
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error=reason),
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )

        result, repository = await _run(fake, CLAUDE)

        assert fake.call_count == 1, "a spent quota was retried"
        assert result.status == "failed"
        message = result.error_message
        assert message is not None
        assert re.search(surfaced, message), message
        assert reason in message, "the CLI's own sentence was dropped"
        assert "not recognised" not in message, message
        assert _failed_kind(repository) is UpstreamFailureKind.QUOTA

    async def test_a_claude_weekly_limit_runs_the_fallback(self) -> None:
        reason, _ = CLAUDE_WEEKLY_LIMITS["resets Oct 15, 8am"]
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error=reason),
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )

        result, _ = await _run(fake, CLAUDE, CODEX_FALLBACK)

        assert result.status == "completed", result.error_message
        assert fake.runners == [AgentRunner.CLAUDE, AgentRunner.CODEX]


class TestTheOtherKindsKeepTheirDecision:
    async def test_codex_at_capacity_is_retried(self) -> None:
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error=CODEX_AT_CAPACITY),
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )

        result, _ = await _run(fake, CODEX)

        assert result.status == "completed", result.error_message
        assert fake.call_count == 2, "a busy upstream was not retried"

    async def test_claude_rate_limited_is_retried(self) -> None:
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error="Rate limited (HTTP 429)"),
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )

        result, _ = await _run(fake, CLAUDE)

        assert result.status == "completed", result.error_message
        assert fake.call_count == 2, "a throttled upstream was not retried"

    async def test_an_unrecognised_failure_is_not_retried(self) -> None:
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(stream_error="Something went wrong"),
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SUCCEEDED),
        )

        result, repository = await _run(fake, CLAUDE)

        assert result.status == "failed"
        assert fake.call_count == 1, "an unrecognised failure was retried"
        assert _failed_kind(repository) is UpstreamFailureKind.UNKNOWN


def test_the_year_is_placed_by_the_reading() -> None:
    """Claude names no year: the reset is the first such time after the reason was read."""
    reason, _ = CLAUDE_WEEKLY_LIMITS["resets Oct 23, 3pm"]
    seen_the_day_before = HarnessUpstreamFailureReader(
        clock=lambda: datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    )

    quota = seen_the_day_before.quota_of(reason)

    assert quota is not None
    assert quota.account() == "claude quota exhausted until 2026-10-23T15:00:00+00:00"
