"""A killed phase keeps the cost it accumulated before it died (#1164).

An agent process that times out or is SIGKILLed never emits the harness's
terminal ``result`` event. The session_summary - the record the cost ledger
treats as authoritative - used to be written straight from that missing
event's fields, so a phase that ran for an hour and made 93 tool calls was
recorded with zero tokens and $0.00. The live projection had reported $0.94
while it ran; the terminal transition threw that away.

These tests run the REAL handler over a REAL stream processor into a REAL
collector, and then price the observations that actually came out, because
every previous version of this bug survived a test that checked the objects
at either end of the hop rather than the value crossing it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import SessionCostProjection
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import price_phase_rows

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )

_MODEL = "claude-opus-4-20250514"
_SESSION_ID = "sess-killed"
_EXECUTION_ID = "exec-84543c5a5df4"
_PHASE_ID = "implement"

#: Three turns the agent genuinely completed before the timeout killed it.
_TURNS = ((40_000, 900), (52_000, 1_400), (61_000, 1_100))


class _RecordingWriter:
    """Captures what Lane 2 was actually told, in order."""

    def __init__(self) -> None:
        self.observations: list[tuple[str, dict[str, Any]]] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        name = getattr(observation_type, "value", observation_type)
        self.observations.append((str(name), data))

    def of_type(self, name: str) -> list[dict[str, Any]]:
        return [data for kind, data in self.observations if kind == name]


class _FakeWorkspace:
    """A workspace whose process emits ``lines`` and then exits with ``exit_code``."""

    id = "ws-1"

    def __init__(self, lines: list[str], exit_code: int) -> None:
        self._lines = lines
        self.last_stream_exit_code = exit_code

    def stream(self, *_args: object, **_kwargs: object) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for line in self._lines:
                yield line

        return gen()

    async def interrupt(self) -> bool:
        return True


def _assistant_turn(msg_id: str, input_tokens: int, output_tokens: int) -> str:
    """One completed turn, as the claude CLI reports it mid-stream."""
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": msg_id,
                "content": [{"type": "text", "text": "working"}],
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            },
        }
    )


def _result_event(input_tokens: int, output_tokens: int, cost: float) -> str:
    """The terminal event a killed process never gets to emit."""
    return json.dumps(
        {
            "type": "result",
            "result": "done",
            "total_cost_usd": cost,
            "duration_ms": 48_000,
            "num_turns": 3,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )


async def _run_phase(lines: list[str], exit_code: int) -> _RecordingWriter:
    """Run the real handler over ``lines`` and return everything Lane 2 recorded."""
    writer = _RecordingWriter()
    collector = ObservabilityCollector(
        writer=writer,  # type: ignore[arg-type]
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        phase_id=_PHASE_ID,
        workspace_id="ws-1",
        agent_model=_MODEL,
    )
    await AgentExecutionHandler(controller=None).handle(
        todo=TodoItem(execution_id=_EXECUTION_ID, action=TodoAction.RUN_AGENT, phase_id=_PHASE_ID),
        workspace=_FakeWorkspace(lines, exit_code),  # type: ignore[arg-type]
        agent_env={},
        claude_cmd=["claude"],
        session_id=_SESSION_ID,
        agent_model=_MODEL,
        timeout_seconds=3600,
        collector=collector,
    )
    return writer


def _summary_of(writer: _RecordingWriter) -> dict[str, Any]:
    summaries = writer.of_type("session_summary")
    assert len(summaries) == 1, f"expected exactly one session_summary, got {len(summaries)}"
    return summaries[0]


class _FakeRow:
    """Stands in for the asyncpg record ``_COST_BY_PHASE_QUERY`` returns."""

    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _phase_row_from_summary(summary: dict[str, Any]) -> _FakeRow:
    """Build the ledger row the SQL aggregation would produce for one summary."""
    return _FakeRow(
        {
            "phase_id": _PHASE_ID,
            "model": summary["model"],
            "total_input": summary["total_input_tokens"],
            "total_output": summary["total_output_tokens"],
            "cache_creation": summary["cache_creation_tokens"],
            "cache_read": summary["cache_read_tokens"],
            "sdk_cost": summary["total_cost_usd"],
            "observation_count": 1,
        }
    )


class TestKilledPhaseKeepsItsTokens:
    @pytest.mark.asyncio
    async def test_timeout_records_the_tokens_it_observed(self) -> None:
        """(a) Killed mid-run, no result event: the summary carries what was seen."""
        lines = [_assistant_turn(f"msg-{i}", inp, out) for i, (inp, out) in enumerate(_TURNS)]
        writer = await _run_phase(lines, exit_code=124)

        observed_input = sum(inp for inp, _ in _TURNS)
        observed_output = sum(out for _, out in _TURNS)
        summary = _summary_of(writer)

        assert summary["total_input_tokens"] == observed_input
        assert summary["total_output_tokens"] == observed_output
        # The point of the issue: not zero.
        assert summary["total_input_tokens"] > 0
        assert summary["total_output_tokens"] > 0
        # And it says so: these are observed totals, not the harness's own.
        assert summary["totals_are_authoritative"] is False

    @pytest.mark.asyncio
    async def test_normal_completion_still_uses_the_harness_totals(self) -> None:
        """(b) A result event still wins - it is not the accumulated sum."""
        lines = [
            *[_assistant_turn(f"msg-{i}", inp, out) for i, (inp, out) in enumerate(_TURNS)],
            _result_event(input_tokens=685, output_tokens=1961, cost=0.0319),
        ]
        writer = await _run_phase(lines, exit_code=0)
        summary = _summary_of(writer)

        # 685/1961, NOT the 153000/3400 the per-turn deltas add up to: the
        # harness's cumulative figure is the authoritative one, and preferring
        # it is exactly what must not regress while fixing the killed case.
        assert summary["total_input_tokens"] == 685
        assert summary["total_output_tokens"] == 1961
        assert summary["total_cost_usd"] == pytest.approx(0.0319)
        assert summary["totals_are_authoritative"] is True
        assert summary["total_input_tokens"] != sum(inp for inp, _ in _TURNS)

    @pytest.mark.asyncio
    async def test_terminal_cost_agrees_with_what_the_live_path_reported(self) -> None:
        """(c) Live and terminal price the same observations to the same number."""
        lines = [_assistant_turn(f"msg-{i}", inp, out) for i, (inp, out) in enumerate(_TURNS)]
        writer = await _run_phase(lines, exit_code=124)

        # LIVE: what the running execution reported, accumulated per observation.
        store: dict[tuple[str, str], dict[str, Any]] = {}

        class _Store:
            async def save(self, name: str, key: str, value: dict[str, Any]) -> None:
                store[(name, key)] = value

            async def get(self, name: str, key: str) -> dict[str, Any] | None:
                return store.get((name, key))

        projection = SessionCostProjection(store=_Store())  # type: ignore[arg-type]
        for usage in writer.of_type("token_usage"):
            await projection.on_agent_observation(
                {
                    "session_id": _SESSION_ID,
                    "execution_id": _EXECUTION_ID,
                    "phase_id": _PHASE_ID,
                    "event_type": "token_usage",
                    "data": usage,
                }
            )
        live_cost = (await projection.get_session_cost(_SESSION_ID)).total_cost_usd  # type: ignore[union-attr]

        # TERMINAL: what the ledger reports for the phase once it has failed.
        phase_costs = price_phase_rows(
            [_phase_row_from_summary(_summary_of(writer))],  # type: ignore[list-item]
            CostCalculator(),
        )
        terminal_cost = phase_costs.cost_by_phase[_PHASE_ID]

        assert live_cost > Decimal("0")
        assert terminal_cost == live_cost, (
            f"terminal ledger says {terminal_cost}, live path said {live_cost}"
        )
        assert phase_costs.unpriced_by_phase.get(_PHASE_ID, 0) == 0

    @pytest.mark.asyncio
    async def test_summary_does_not_wipe_the_projections_running_totals(self) -> None:
        """The terminal transition must not reset a session that was counting."""
        lines = [_assistant_turn(f"msg-{i}", inp, out) for i, (inp, out) in enumerate(_TURNS)]
        writer = await _run_phase(lines, exit_code=124)

        store: dict[tuple[str, str], dict[str, Any]] = {}

        class _Store:
            async def save(self, name: str, key: str, value: dict[str, Any]) -> None:
                store[(name, key)] = value

            async def get(self, name: str, key: str) -> dict[str, Any] | None:
                return store.get((name, key))

        projection = SessionCostProjection(store=_Store())  # type: ignore[arg-type]
        for usage in writer.of_type("token_usage"):
            await projection.on_agent_observation(
                {
                    "session_id": _SESSION_ID,
                    "event_type": "token_usage",
                    "data": usage,
                }
            )
        running = await projection.get_session_cost(_SESSION_ID)
        assert running is not None
        running_cost, running_input = running.total_cost_usd, running.input_tokens
        assert running.turns == len(_TURNS)

        await projection.on_session_summary(
            {
                "session_id": _SESSION_ID,
                "execution_id": _EXECUTION_ID,
                "phase_id": _PHASE_ID,
                "timestamp": "2026-01-01T23:56:48",
                "data": _summary_of(writer),
            }
        )

        settled = await projection.get_session_cost(_SESSION_ID)
        assert settled is not None
        assert settled.input_tokens == running_input
        assert settled.total_cost_usd == running_cost
        # A killed phase reports no turn count and no duration - the summary
        # carries None for both. Assigning that over the counted values put
        # None into an int field and threw away the turns the phase really
        # took, which no test noticed because both ends of the hop agreed.
        assert settled.turns == len(_TURNS)
        assert settled.duration_ms == running.duration_ms
        # A phase that was killed before reporting has not settled its bill,
        # and the dashboard's "Finalized" badge must not claim it has.
        assert settled.is_finalized is False
