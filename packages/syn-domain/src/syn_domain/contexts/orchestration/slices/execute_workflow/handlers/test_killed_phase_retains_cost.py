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
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.agent_sessions import SessionSummaryData, TokenUsageData
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
from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )

pytestmark = pytest.mark.unit

_MODEL = "claude-opus-4-20250514"
_SESSION_ID = "sess-killed"
_EXECUTION_ID = "exec-84543c5a5df4"
_PHASE_ID = "implement"

#: Three turns the agent genuinely completed before the timeout killed it.
_TURNS = ((40_000, 900), (52_000, 1_400), (61_000, 1_100))


class _RecordingWriter:
    """Captures what Lane 2 was actually told, filed by payload shape.

    These tests read back the two observation kinds the cost ledger is built
    from, so those are kept as their declared payload types and anything else
    is kept by name only - enough to notice an unexpected recording without
    claiming to know its shape. ``observation_type`` is the discriminator, so
    the casts below are justified by the same key the real consumers dispatch on.
    """

    def __init__(self) -> None:
        self.summaries: list[SessionSummaryData] = []
        self.token_usages: list[TokenUsageData] = []
        self.other_kinds: list[str] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: SessionSummaryData | TokenUsageData,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        kind = str(getattr(observation_type, "value", observation_type))
        if kind == SESSION_SUMMARY:
            self.summaries.append(cast("SessionSummaryData", data))
        elif kind == TOKEN_USAGE:
            self.token_usages.append(cast("TokenUsageData", data))
        else:
            self.other_kinds.append(kind)

    @property
    def summary(self) -> SessionSummaryData:
        """The one summary the phase recorded.

        A phase emits exactly one, and a test that silently read the first of
        two would be asserting about whichever ran first.
        """
        assert len(self.summaries) == 1, (
            f"expected exactly one session_summary, got {len(self.summaries)}"
        )
        return self.summaries[0]


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


class _InMemoryStore[RowT]:
    """The projection store, kept in memory for the life of one test.

    Rows are opaque on purpose: the real store round-trips whatever the
    projection serialised, and that round-trip is the property these tests
    lean on. A fake that named the row's shape would be asserting something
    the real store does not, and a fake that reshaped it would hide the hop.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], RowT] = {}

    async def save(self, name: str, key: str, value: RowT) -> None:
        self._rows[(name, key)] = value

    async def get(self, name: str, key: str) -> RowT | None:
        return self._rows.get((name, key))


class _FakeRow:
    """Stands in for the asyncpg record ``_COST_BY_PHASE_QUERY`` returns."""

    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _phase_row_from_summary(summary: SessionSummaryData) -> _FakeRow:
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
        summary = writer.summary

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
        summary = writer.summary

        # 685/1961, NOT the 153000/3400 the per-turn deltas add up to: the
        # harness's cumulative figure is the authoritative one, and preferring
        # it is exactly what must not regress while fixing the killed case.
        assert summary["total_input_tokens"] == 685
        assert summary["total_output_tokens"] == 1961
        assert summary["total_cost_usd"] == pytest.approx(0.0319)
        assert summary["totals_are_authoritative"] is True
        assert summary["total_input_tokens"] != sum(inp for inp, _ in _TURNS)

    @pytest.mark.asyncio
    async def test_a_run_that_genuinely_used_nothing_keeps_its_own_zero(self) -> None:
        """A reported 0/0 is an ANSWER, and must not be read as "never reported".

        The distinction the whole fix rests on. This phase did emit its terminal
        `result` event, and that event says zero - so zero is authoritative and
        REPLACES the 17/9 the accumulator saw. Deciding by magnitude
        (`bool(input or output)`) cannot tell this stream from a SIGKILLed one,
        so it fell through to the accumulator and reported 17/9 as final for a
        run the harness had already settled at 0/0.
        """
        lines = [
            _assistant_turn("msg-0", 17, 9),
            _result_event(input_tokens=0, output_tokens=0, cost=0.0),
        ]
        writer = await _run_phase(lines, exit_code=0)

        # The accumulator really did have something to win with - without an
        # observed 17/9 to be wrongly preferred, this test proves nothing.
        assert writer.token_usages == [
            TokenUsageData(
                input_tokens=17,
                output_tokens=9,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                model=_MODEL,
            )
        ]

        summary = writer.summary
        assert (summary["total_input_tokens"], summary["total_output_tokens"]) == (0, 0)
        assert summary["totals_are_authoritative"] is True

    @pytest.mark.asyncio
    async def test_the_ledger_settles_a_genuine_zero_instead_of_estimating_it(self) -> None:
        """The consuming hop: a reported zero settles the session at zero.

        Asserted on the projection, not on the summary dict, because the summary
        is one hop short of where the flag is spent: `is_finalized` is what the
        dashboard badge and the cost ledger read. Under the magnitude check this
        session came out 17/9 and NOT finalized - wrong number and wrong status,
        from a run that had reported its own final answer.
        """
        lines = [
            _assistant_turn("msg-0", 17, 9),
            _result_event(input_tokens=0, output_tokens=0, cost=0.0),
        ]
        writer = await _run_phase(lines, exit_code=0)

        projection = SessionCostProjection(store=_InMemoryStore())  # type: ignore[arg-type]
        for usage in writer.token_usages:
            await projection.on_agent_observation(
                {"session_id": _SESSION_ID, "event_type": "token_usage", "data": usage}
            )
        counted = await projection.get_session_cost(_SESSION_ID)
        assert counted is not None
        assert (counted.input_tokens, counted.output_tokens) == (17, 9)

        await projection.on_session_summary(
            {
                "session_id": _SESSION_ID,
                "execution_id": _EXECUTION_ID,
                "phase_id": _PHASE_ID,
                "timestamp": "2026-01-01T23:56:48",
                "data": writer.summary,
            }
        )

        settled = await projection.get_session_cost(_SESSION_ID)
        assert settled is not None
        assert (settled.input_tokens, settled.output_tokens) == (0, 0)
        assert settled.is_finalized is True

    @pytest.mark.asyncio
    async def test_terminal_cost_agrees_with_what_the_live_path_reported(self) -> None:
        """(c) Live and terminal price the same observations to the same number."""
        lines = [_assistant_turn(f"msg-{i}", inp, out) for i, (inp, out) in enumerate(_TURNS)]
        writer = await _run_phase(lines, exit_code=124)

        # LIVE: what the running execution reported, accumulated per observation.
        projection = SessionCostProjection(store=_InMemoryStore())  # type: ignore[arg-type]
        for usage in writer.token_usages:
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
            [_phase_row_from_summary(writer.summary)],  # type: ignore[list-item]
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

        projection = SessionCostProjection(store=_InMemoryStore())  # type: ignore[arg-type]
        for usage in writer.token_usages:
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
                "data": writer.summary,
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
