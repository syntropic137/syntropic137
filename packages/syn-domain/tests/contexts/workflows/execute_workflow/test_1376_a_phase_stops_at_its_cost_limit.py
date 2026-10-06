"""#1376: a phase has a cost limit, and crossing it stops the phase.

exec-d9ec05de3174 spent USD 77.35 in one phase before `timeout_seconds` ended
it: parallel subagents turn a time bound into an unbounded cost. These pin the
whole path of the bound that closes that, each at the hop that CONSUMES it:

- the YAML refuses a limit that cannot bound anything, and the one it accepts
  reaches the stored phase definition;
- the limit declared on the phase reaches the agent run;
- the stream stops the agent on the turn that crosses it, priced by the one
  pricing entry point;
- the stop reaches the aggregate as a FAILED execution naming the limit and
  the spend - not a cancel, which would refuse resume.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import PhaseYamlDefinition
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import WorkflowDetail
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
    PhaseCostLimit,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_shared.agents import ModelId
from syn_shared.pricing import price_tokens

from .test_processor_smoke import _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

MODEL = ModelId.CLAUDE_OPUS_5_5.value
#: Per turn. Large enough that two turns cross a USD 1.00 limit at any
#: plausible rate for this model and one turn does not.
TURN_INPUT_TOKENS = 150_000


def _turn(message_id: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": message_id,
                "model": MODEL,
                "content": [{"type": "text", "text": "working"}],
                "usage": {"input_tokens": TURN_INPUT_TOKENS, "output_tokens": 0},
            },
        }
    )


async def _stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


@dataclass
class _Workspace:
    interrupted: bool = False

    async def interrupt(self) -> bool:
        self.interrupted = True
        return True


def _processor(cost_limit: PhaseCostLimit | None) -> EventStreamProcessor:
    return EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-1376",
        phase_id="experiment",
        session_id="session-1376",
        workspace_id="ws-1376",
        agent_model=MODEL,
        cost_limit=cost_limit,
    )


def _turn_cost() -> float:
    priced = price_tokens(MODEL, TURN_INPUT_TOKENS, 0)
    assert priced.cost is not None, f"{MODEL} must be priced for this test to mean anything"
    return float(priced.cost)


def _limit_between_one_and_two_turns() -> float:
    return round(_turn_cost() * 1.5, 2)


class TestTheYamlValidatesTheLimit:
    def _phase(self, **extra: object) -> PhaseYamlDefinition:
        return PhaseYamlDefinition.model_validate(
            {"id": "experiment", "name": "Experiment", "order": 1, **extra}
        )

    @pytest.mark.parametrize("bad", [0, -1.0, math.inf, math.nan])
    def test_a_limit_that_bounds_nothing_is_refused_at_install(self, bad: float) -> None:
        with pytest.raises(ValidationError, match="max_cost_usd"):
            self._phase(max_cost_usd=bad)

    def test_the_accepted_limit_reaches_the_stored_phase_definition(self) -> None:
        definition = self._phase(max_cost_usd=12.5).to_domain()

        assert definition.max_cost_usd == 12.5

    def test_the_limit_survives_the_workflow_read_model_round_trip(self) -> None:
        """`to_dict` is what is stored and `from_dict` what every reader uses."""
        definition = self._phase(max_cost_usd=12.5).to_domain()
        stored = WorkflowDetail.from_dict(
            {"id": "wf", "name": "wf", "phases": [definition.model_dump()]}
        ).to_dict()

        read_back = WorkflowDetail.from_dict(stored)

        assert read_back.phases[0].max_cost_usd == 12.5


class TestTheStreamStopsTheAgent:
    @pytest.mark.anyio
    async def test_the_turn_that_crosses_the_limit_interrupts_the_agent(self) -> None:
        limit = _limit_between_one_and_two_turns()
        workspace = _Workspace()

        result = await _processor(PhaseCostLimit(limit)).process_stream(
            _stream(_turn("m1"), _turn("m2"), _turn("m3")), workspace
        )

        assert workspace.interrupted
        assert result.interrupt_requested
        assert result.line_count == 2, "the stream must stop on the crossing turn"
        assert result.cost_limit_reason == (
            f"cost limit USD {limit:.2f} exceeded at USD {2 * _turn_cost():.2f}"
        )

    @pytest.mark.anyio
    async def test_a_turn_replayed_under_the_same_message_id_is_not_spent_twice(self) -> None:
        workspace = _Workspace()

        result = await _processor(
            PhaseCostLimit(_limit_between_one_and_two_turns())
        ).process_stream(_stream(_turn("m1"), _turn("m1"), _turn("m1")), workspace)

        assert not workspace.interrupted
        assert result.cost_limit_reason is None

    @pytest.mark.anyio
    async def test_a_phase_with_no_limit_is_never_stopped_for_cost(self) -> None:
        workspace = _Workspace()

        result = await _processor(None).process_stream(
            _stream(_turn("m1"), _turn("m2"), _turn("m3")), workspace
        )

        assert not workspace.interrupted
        assert result.cost_limit_reason is None
        assert result.line_count == 3


class TestTheStopIsAFailureOnTheExecution:
    @pytest.mark.anyio
    async def test_the_declared_limit_reaches_the_agent_run(self) -> None:
        handler = FakeAgentExecutionHandler.success()
        phase = replace(_one_phase_workflow()[0], max_cost_usd=3.25)

        await _make_processor(handler).run(
            workflow_id="wf-1376",
            workflow_name="Cost limit reaches the run",
            phases=[phase],
            inputs={},
            execution_id="exec-1376-reach",
        )

        [limit] = handler.cost_limits
        assert limit is not None
        assert limit.exceeded() is None
        limit.record_turn(MODEL, 10_000_000, 0)
        assert limit.exceeded() is not None
        assert "USD 3.25" in (limit.exceeded() or "")

    @pytest.mark.anyio
    async def test_no_limit_declared_hands_the_run_none(self) -> None:
        handler = FakeAgentExecutionHandler.success()

        await _make_processor(handler).run(
            workflow_id="wf-1376",
            workflow_name="No limit",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1376-none",
        )

        assert handler.cost_limits == [None]

    @pytest.mark.anyio
    async def test_a_cost_stop_fails_the_execution_with_its_reason(self) -> None:
        reason = "cost limit USD 5.00 exceeded at USD 5.43"
        processor = _make_processor(FakeAgentExecutionHandler.stopped_on_cost(reason))
        repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
        recorded: list[object] = []
        original_save = repository.save

        async def capturing_save(aggregate: object) -> None:
            recorded.extend(e.event for e in aggregate.get_uncommitted_events())  # pyright: ignore[reportAttributeAccessIssue]
            await original_save(aggregate)

        repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

        result = await processor.run(
            workflow_id="wf-1376",
            workflow_name="Cost stop",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1376-stop",
        )

        # FAILED, not cancelled: a cancelled execution refuses resume.
        assert result.status == "failed"
        names = [type(e).__name__ for e in recorded]
        assert "ExecutionCancelledEvent" not in names
        [failed] = [e for e in recorded if type(e).__name__ == "WorkflowFailedEvent"]
        payload = ExecutionJournal._serialize_event(failed)  # pyright: ignore[reportPrivateUsage]
        assert reason in payload["error_message"]
        assert payload["failed_phase_id"] == "phase-001"
        assert payload["failure_classification"] == "platform"
