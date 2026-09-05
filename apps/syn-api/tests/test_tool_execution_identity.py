"""Guard: every tool_execution row reaches the stats aggregation identified.

`_accumulate_tool_stats` (`syn_api.routes.events`) dedupes a start row and its
completion row by `op.tool_use_id or op.observation_id`. Only the first half of
that expression is a real identity. `observation_id` is synthesized per row
from the row's own timestamp (`session_tools_dispatch._build_standard_operation`),
so two rows of one logical call get different values and would be counted as
two calls - the exact #1061 double-count.

That fallback is unreachable for tool events today, and this module is what
keeps it unreachable. Both stream processors read the harness's own id off the
stream item and carry it through the collector into the stored payload, so
`tool_use_id` is always present by the time the aggregation sees it. A
production census over 48,011 `tool_execution_started`/`tool_execution_completed`
rows found zero missing it, which is a measurement of that behaviour, not a
guarantee of it - nothing in the code enforced it and nothing failed if it
stopped. These tests are that enforcement: they drive the real producers over
real stream input and assert the harness's id survives every hop down to the
aggregation.

Why they assert the id and not only `call_count == 1`: both processors default
a missing id to the literal string `"unknown"`
(`EventStreamProcessor._handle_tool_use`, `CodexStreamProcessor._handle_item_started`).
That sentinel is truthy and identical across rows, so a broken id path still
dedupes a pair to one call and a count-only assertion would stay green while
every distinct unidentified call silently collapsed into one bucket. Pinning
the id to the value the harness actually sent is what makes the regression
loud.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from json import dumps
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_adapters.events.models import AgentEvent
from syn_adapters.projections.session_tools import SessionToolsProjection, ToolOperation
from syn_api.routes.events import _accumulate_tool_stats
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
from syn_shared.codex_stream import CODEX_TOOL_NAME_COMMAND, CODEX_TOOL_NAME_FILE_CHANGE
from syn_shared.events import TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

pytestmark = pytest.mark.unit

# The golden `codex exec --json` capture, real output from a real run. Shared
# with test_codex_stream_processor.py rather than hand-rolled here: a guard on
# what the harness emits is only worth as much as the input it is fed.
_CODEX_RECORDING = (
    Path(__file__).resolve().parents[3]
    / "packages/syn-domain/tests/fixtures/codex/codex_exec_recording.jsonl"
)

_SESSION_ID = "session-under-test"
_FIRST_ROW_TIME = datetime(2026, 1, 1, tzinfo=UTC)
_TOOL_EVENT_TYPES = (TOOL_EXECUTION_STARTED, TOOL_EXECUTION_COMPLETED)


@dataclass(frozen=True)
class _Observation:
    """One `record_observation` call, as the producer made it."""

    event_type: str
    payload: Mapping[str, object]


@dataclass
class _CapturingWriter:
    """Stands in for the observability store, keeping what the producer wrote."""

    observations: list[_Observation] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: object,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        event_type = getattr(observation_type, "value", observation_type)
        self.observations.append(_Observation(str(event_type), dict(data)))


class _NoopWorkspace:
    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


async def _stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


def _tool_operations(observations: Sequence[_Observation]) -> list[ToolOperation]:
    """Replay recorded observations forward to what the aggregation sees.

    Mirrors the two hops between the producer and the read model: the store
    flattens the payload and normalises it through `AgentEvent.from_dict`
    before writing (`store_helpers.record_observation` -> `store_write.insert_one`),
    and the projection converts the stored row back into a `ToolOperation`.

    Rows get distinct, increasing timestamps because production rows do. A
    start and its completion sharing one timestamp would give them the same
    synthesized `observation_id` and hide an unidentified pair behind an
    accidentally-correct count - which is how this defect survived an earlier
    review round.
    """
    operations: list[ToolOperation] = []
    for offset, observation in enumerate(observations):
        row_time = _FIRST_ROW_TIME + timedelta(seconds=offset)
        stored = AgentEvent.from_dict(
            {
                "event_type": observation.event_type,
                "session_id": _SESSION_ID,
                "timestamp": row_time,
                **observation.payload,
            }
        )
        if stored.event_type not in _TOOL_EVENT_TYPES:
            continue
        row = {"event_type": stored.event_type, "time": row_time, "data": stored.data}
        operation = SessionToolsProjection()._row_to_operation(row)
        assert operation is not None
        operations.append(operation)
    return operations


async def test_claude_tool_call_carries_its_harness_id_to_the_aggregation() -> None:
    """A Claude `tool_use`/`tool_result` pair, from the CLI stream to the summary.

    `toolu_01ABC` is the id the harness put on the stream. It can only appear
    on both operations if every hop carried it: `_handle_tool_use` and
    `_handle_tool_result` read it off the item, `ObservabilityCollector` puts
    it in the payload, `AgentEvent.from_dict` keeps it, and the projection
    reads it back. Drop it anywhere and the id becomes `"unknown"` (the
    processors' default) or absent - both caught here, only the second one
    caught by the call count.
    """
    writer = _CapturingWriter()
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=writer,
        controller=None,
        execution_id="exec-1",
        phase_id="phase-1",
        session_id=_SESSION_ID,
        workspace_id="ws-1",
        agent_model="claude-sonnet",
    )
    tool_use = dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_01ABC",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    }
                ],
            },
        }
    )
    tool_result = dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_01ABC",
                        "content": "ok",
                        "is_error": False,
                    }
                ]
            },
        }
    )

    await processor.process_stream(_stream(tool_use, tool_result), _NoopWorkspace())
    operations = _tool_operations(writer.observations)

    assert [op.operation_type for op in operations] == [
        TOOL_EXECUTION_STARTED,
        TOOL_EXECUTION_COMPLETED,
    ]
    assert [op.tool_use_id for op in operations] == ["toolu_01ABC", "toolu_01ABC"]

    stats = _accumulate_tool_stats(operations)
    assert stats["Bash"]["call_count"] == 1
    assert stats["Bash"]["success_count"] == 1


async def test_codex_recording_carries_its_harness_ids_to_the_aggregation() -> None:
    """The same guard for the codex harness, over its golden recording.

    The recording contains six items; `item_1` and `item_3` are `file_change`,
    `item_2` and `item_4` are `command_execution`, and `item_0`/`item_5` are
    `agent_message` and are not tool calls. So four logical calls, eight rows,
    each row carrying the item id codex assigned it.
    """
    writer = _CapturingWriter()
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=ObservabilityCollector(
            writer=writer,
            session_id=_SESSION_ID,
            execution_id="exec-1",
            phase_id="phase-1",
            workspace_id="ws-1",
            agent_model="gpt-5.6",
        ),
        controller=None,
        execution_id="exec-1",
        phase_id="phase-1",
        session_id=_SESSION_ID,
        agent_model="gpt-5.6",
    )

    await processor.process_stream(
        _stream(*_CODEX_RECORDING.read_text().splitlines()), _NoopWorkspace()
    )
    operations = _tool_operations(writer.observations)

    assert [op.tool_use_id for op in operations] == [
        "item_1",
        "item_1",
        "item_2",
        "item_2",
        "item_3",
        "item_3",
        "item_4",
        "item_4",
    ]

    stats = _accumulate_tool_stats(operations)
    assert stats[CODEX_TOOL_NAME_FILE_CHANGE]["call_count"] == 2
    assert stats[CODEX_TOOL_NAME_COMMAND]["call_count"] == 2
