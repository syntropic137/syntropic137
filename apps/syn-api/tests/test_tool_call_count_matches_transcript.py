"""The tool summary counts exactly the transcript's tool calls.

Ground truth for "how many tool calls did this session make" is the harness's
own transcript: one `tool_use` content block per call (see "Tool call" in
docs/architecture/agent_sessions-ubiquitous-language.md). An evaluation that
compares runs on tool usage reads `GET /events/sessions/{id}/tools`, so that
endpoint's counts must equal the transcript's, tool by tool.

They did not. A real session (exec-7a1c3cd472ea, 2026-10-03) reported Bash 53
against 36 `tool_use` blocks, plus "tools" named checkout, commit, push and
unknown that the agent never called. Two defects, both reproduced here on real
input:

- `EmbeddedEventScanner` recorded ANY known event type it found as a line of
  tool output, not only the git-hook events it exists for (ADR-043). An agent
  that prints recorded events - `cat` on an events file, a test run, a log -
  had every `tool_execution_started` line in that output stored as one of its
  own calls, under the foreign row's tool name and tool_use_id.
- `_accumulate_tool_stats` counted every timeline row as a call: git
  operations (already counted once, as the Bash call that ran `git`) and
  session/phase lifecycle rows, which have no tool name and showed up as
  "unknown".

Fixture provenance: `v2.1.281_session_transcript_tool_calls.jsonl` is the
native transcript of a real Claude Code 2.1.281 session (the workspace session
that wrote this fix, native id d81dacdd-9907-4250-aa74-b814e2ecc4b5), reduced
to its `assistant`/`user` lines that carry `tool_use`/`tool_result` blocks.
Every line keeps its `version` field. Those message objects are what the
stream-json `assistant`/`user` lines carry; the recording could not be taken
from `--output-format stream-json` directly because the nested CLI in the
workspace is not logged in. The tool outputs are real: one carries the
`git_checkout` JSONL the workspace's git hook printed, another carries
`tool_execution_started`/`completed` lines the agent printed while
investigating - the exact shape of the defect.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_adapters.events.models import AgentEvent
from syn_adapters.projections.session_tools import (
    TIMELINE_EXCLUDE,
    SessionToolsProjection,
    ToolOperation,
)
from syn_api.routes.events import _accumulate_tool_stats
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.events import GIT_CHECKOUT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

pytestmark = pytest.mark.unit

_RECORDING = (
    Path(__file__).resolve().parents[3]
    / "packages/syn-domain/tests/fixtures/claude/v2.1.281_session_transcript_tool_calls.jsonl"
)
_SESSION_ID = "session-under-test"
_FIRST_ROW_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class _Observation:
    event_type: str
    payload: Mapping[str, object]


@dataclass
class _CapturingWriter:
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


async def _stream(lines: Sequence[str]) -> AsyncIterator[str]:
    for line in lines:
        yield line


def _transcript_tool_calls(lines: Sequence[str]) -> Counter[str]:
    """Count `tool_use` blocks by tool name - the definition, read directly."""
    calls: Counter[str] = Counter()
    for line in lines:
        message = json.loads(line).get("message") or {}
        for block in message.get("content") or []:
            if block.get("type") == "tool_use":
                calls[block["name"]] += 1
    return calls


def _timeline(observations: Sequence[_Observation]) -> list[ToolOperation]:
    """Every stored row the session timeline returns, as the summary reads it.

    The same hops as production: `AgentEvent.from_dict` normalises the payload
    before the write, the timeline query drops `TIMELINE_EXCLUDE`, and the
    projection converts each remaining row. Nothing is pre-filtered to tool
    events here - deciding what is a call is the code under test.
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
        if stored.event_type in TIMELINE_EXCLUDE:
            continue
        row = {"event_type": stored.event_type, "time": row_time, "data": stored.data}
        operation = SessionToolsProjection()._row_to_operation(row)
        if operation is not None:
            operations.append(operation)
    return operations


async def _replay(lines: Sequence[str]) -> list[_Observation]:
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
        agent_model="claude-opus-5-5",
    )
    await processor.process_stream(_stream(lines), _NoopWorkspace())
    return writer.observations


async def test_tool_summary_counts_equal_the_transcript_tool_use_counts() -> None:
    lines = _RECORDING.read_text().splitlines()
    assert {json.loads(line)["version"] for line in lines} == {"2.1.281"}
    expected = _transcript_tool_calls(lines)
    # The recording must actually exercise both defects, or this proves nothing.
    assert '\\"event_type\\": \\"tool_execution_started\\"' in _RECORDING.read_text()
    assert f'\\"event_type\\": \\"{GIT_CHECKOUT}\\"' in _RECORDING.read_text()

    observations = await _replay(lines)
    stats = _accumulate_tool_stats(_timeline(observations))

    assert {name: int(s["call_count"]) for name, s in stats.items()} == dict(expected)


async def test_git_hook_events_in_tool_output_are_still_recorded() -> None:
    """The scanner's real job survives the narrowing: the git hook's checkout
    is stored, as a git row, and the foreign tool rows printed beside it are
    not stored at all."""
    observations = await _replay(_RECORDING.read_text().splitlines())
    recorded = [o.event_type for o in observations]

    assert GIT_CHECKOUT in recorded
    assert not any(
        o.payload.get("tool_use_id") == "toolu_FOREIGN" for o in observations
    ), "a tool row printed by the agent was recorded as the agent's own call"
