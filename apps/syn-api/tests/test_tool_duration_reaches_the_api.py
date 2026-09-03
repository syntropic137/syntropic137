"""Per-tool duration must survive from the stream parser to ``/sessions/{id}/tools``.

Issue #1064: ``total_duration_ms`` was 0 for every tool of every session on the
deployment. The read path was already correct - the projection reads
``data["duration_ms"]`` and the API sums it - but nothing ever wrote the field,
so the API divided a zero numerator and reported a confident zero.

The bug lived entirely in the gaps BETWEEN layers, which is why every existing
test missed it: the collector wrote a well-formed observation, the projection
faithfully converted a well-formed row, and the API faithfully summed
well-formed operations. Each hop was right about the object it was handed.

So these tests run the whole chain for real - stream bytes in, API numbers out:

    JSONL line -> {EventStream,Codex}StreamProcessor
               -> ObservabilityCollector (writes the observation payload)
               -> row_to_operation           (syn_adapters projection)
               -> _accumulate_tool_stats     (syn_api aggregation)
               -> total_duration_ms / avg_duration_ms

The clock is scripted so the expected millisecond value is one that could not
arise by accident: 1500 and 4000 ms cannot come from a wall clock inside a
test, and they cannot come from the ``None`` the code produced before the fix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projections.session_tools_dispatch import row_to_operation
from syn_api.routes.events import _accumulate_tool_stats
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from syn_adapters.projections.session_tools import ToolOperation

SESSION_ID = "session-1064"

# Scripted clock readings, in seconds. Each pair is one tool op: the collector
# reads the clock once at record_tool_started and once at record_tool_completed.
CLAUDE_TOOL_MS = 1500
CODEX_TOOL_MS = 4000


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedClock:
    """Returns the scripted readings in order, then holds the last one.

    A fake rather than a real clock so the asserted duration is an exact
    number the test chose, not a timing measurement that happens to be
    positive.
    """

    readings: list[float]
    _index: int = 0

    def __call__(self) -> float:
        reading = self.readings[min(self._index, len(self.readings) - 1)]
        self._index += 1
        return reading


@dataclass(frozen=True)
class _Observation:
    """One observation as the observability store would see it."""

    event_type: str
    data: Mapping[str, object]


@dataclass
class _RecordingWriter:
    """Captures what the collector actually wrote, as the store would see it."""

    observations: list[_Observation] = field(default_factory=list)

    def completions(self) -> list[Mapping[str, object]]:
        """Payloads of the ``tool_execution_completed`` observations, in order."""
        completed = ObservationType.TOOL_EXECUTION_COMPLETED
        return [o.data for o in self.observations if o.event_type == completed]

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        event_type = (
            observation_type.value
            if isinstance(observation_type, ObservationType)
            else observation_type
        )
        self.observations.append(_Observation(event_type=event_type, data=dict(data)))


class _NoopWorkspace:
    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


async def _lines(*raw: str) -> AsyncIterator[str]:
    for line in raw:
        yield line


# ---------------------------------------------------------------------------
# The read path, driven exactly as production drives it
# ---------------------------------------------------------------------------


def _as_rows(writer: _RecordingWriter) -> list[Mapping[str, object]]:
    """Turn captured observations into the row shape the projection reads.

    ``row_to_operation`` takes an ``asyncpg.Record``; a read-only mapping with
    the same three keys is indistinguishable to it. ``time`` is deliberately a
    constant: if the duration came from row timestamps rather than the payload,
    every assertion below would read zero.
    """
    frozen = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    return [
        {"event_type": o.event_type, "time": frozen, "data": o.data} for o in writer.observations
    ]


def _tool_operations(writer: _RecordingWriter) -> list[ToolOperation]:
    return [
        op
        for row in _as_rows(writer)
        if (op := row_to_operation(row, subagent_tool_names=set(), git_event_types=())) is not None
    ]


def _api_stats(writer: _RecordingWriter, tool_name: str) -> tuple[float, float]:
    """Return (total_duration_ms, avg_duration_ms) as ``/sessions/{id}/tools`` does."""
    stats = _accumulate_tool_stats(_tool_operations(writer))[tool_name]
    total = float(stats["total_duration_ms"])
    call_count = int(stats["call_count"])
    return total, (total / call_count if call_count else 0.0)


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------


def _collector(writer: _RecordingWriter, clock: _ScriptedClock) -> ObservabilityCollector:
    return ObservabilityCollector(
        writer=writer,
        session_id=SESSION_ID,
        execution_id="exec-1",
        phase_id="phase-1",
        workspace_id="ws-1",
        agent_model="claude-sonnet",
        clock=clock,
    )


async def _run_claude(*raw: str, clock: _ScriptedClock) -> _RecordingWriter:
    writer = _RecordingWriter()
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-1",
        phase_id="phase-1",
        session_id=SESSION_ID,
        workspace_id="ws-1",
        agent_model="claude-sonnet",
        collector=_collector(writer, clock),
    )
    await processor.process_stream(_lines(*raw), _NoopWorkspace())
    return writer


async def _run_codex(*raw: str, clock: _ScriptedClock) -> _RecordingWriter:
    writer = _RecordingWriter()
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_collector(writer, clock),
        controller=None,
        execution_id="exec-1",
        phase_id="phase-1",
        session_id=SESSION_ID,
        agent_model="gpt-5.6",
    )
    await processor.process_stream(_lines(*raw), _NoopWorkspace())
    return writer


def _claude_tool_lines() -> tuple[str, str]:
    """One Bash tool: the assistant's tool_use, then the user's tool_result."""
    use = json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg_1064",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1064",
                        "name": "Bash",
                        "input": {"command": "pytest -q"},
                    }
                ],
            },
        }
    )
    result = json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1064",
                        "content": "42 passed",
                    }
                ]
            },
        }
    )
    return use, result


def _codex_command_lines(item_id: str = "item_1064") -> tuple[str, str]:
    started = json.dumps(
        {
            "type": "item.started",
            "item": {"id": item_id, "type": "command_execution", "command": "pytest -q"},
        }
    )
    completed = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": item_id,
                "type": "command_execution",
                "command": "pytest -q",
                "exit_code": 0,
                "aggregated_output": "42 passed",
            },
        }
    )
    return started, completed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.regression
class TestDurationSurvivesToTheApi:
    @pytest.mark.asyncio
    async def test_claude_tool_duration_reaches_total_and_average(self) -> None:
        """A Claude tool that ran 1.5s must be 1500ms at the API, not 0."""
        writer = await _run_claude(*_claude_tool_lines(), clock=_ScriptedClock([10.0, 11.5]))

        total, average = _api_stats(writer, "Bash")

        assert total == CLAUDE_TOOL_MS
        assert average == CLAUDE_TOOL_MS / 2  # started + completed rows both counted (#1063)

    @pytest.mark.asyncio
    async def test_codex_tool_duration_reaches_total_and_average(self) -> None:
        """The same guarantee for the codex harness, which has its own parser."""
        writer = await _run_codex(*_codex_command_lines(), clock=_ScriptedClock([100.0, 104.0]))

        total, average = _api_stats(writer, "Bash")

        assert total == CODEX_TOOL_MS
        assert average == CODEX_TOOL_MS / 2

    @pytest.mark.asyncio
    async def test_truncated_codex_stream_reports_unknown_not_zero(self) -> None:
        """A completion whose ``item.started`` never arrived has no duration.

        ``CodexStreamProcessor`` tolerates this by design, so the collector must
        too: the answer is "unknown" (None), which the API already treats as
        contributing nothing, rather than a fabricated elapsed time measured
        from some other tool's start.
        """
        _, completed = _codex_command_lines()
        writer = await _run_codex(completed, clock=_ScriptedClock([100.0, 104.0]))

        assert [d["duration_ms"] for d in writer.completions()] == [None]

        total, _average = _api_stats(writer, "Bash")
        assert total == 0.0

    @pytest.mark.asyncio
    async def test_durations_are_not_cross_attributed_between_tools(self) -> None:
        """Two overlapping tools each get their OWN elapsed time.

        A single "last started" timestamp instead of a per-``tool_use_id`` one
        would pass every single-tool test above and silently report the wrong
        number the moment an agent ran two tools.
        """
        first_started, first_completed = _codex_command_lines("item_a")
        second_started, second_completed = _codex_command_lines("item_b")
        writer = await _run_codex(
            first_started,  # clock 0.0
            second_started,  # clock 1.0
            second_completed,  # clock 2.0 -> item_b ran 1000ms
            first_completed,  # clock 9.0 -> item_a ran 9000ms
            clock=_ScriptedClock([0.0, 1.0, 2.0, 9.0]),
        )

        by_id = {d["tool_use_id"]: d["duration_ms"] for d in writer.completions()}
        assert by_id == {"item_a": 9000, "item_b": 1000}

        total, _average = _api_stats(writer, "Bash")
        assert total == 10_000.0
