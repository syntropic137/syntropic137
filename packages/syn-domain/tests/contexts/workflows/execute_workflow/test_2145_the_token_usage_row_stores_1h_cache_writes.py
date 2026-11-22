"""#2145 slice B2a: the stored ``token_usage`` observation records a turn's 1-hour cache writes.

B1 priced a live turn's 1-hour cache writes at the 1-hour rate, but only in the
phase limiter: the stored row kept the total alone, so nothing read later can
tell a 1-hour write from a 5-minute one. These drive a real turn through the
stream processor and the real collector, and read the row the WRITER received,
which is the hop the cost projections will read from in B2b.

``cache_creation_tokens`` keeps meaning the TOTAL, so every existing reader and
every legacy row reads the same. ``cache_creation_1h_tokens`` is the 1-hour
share of it, and is always written: 0 when the turn reported no split, or a
split that could not be trusted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
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
from syn_shared.agents import ModelId

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import TokenUsageData

pytestmark = pytest.mark.unit

MODEL = ModelId.CLAUDE_OPUS_5_5.value
#: 1000 cache-write tokens: 600 at the 1-hour TTL, 400 at the 5-minute one.
#: Neither share equals the total, so a row storing either share in place of
#: the total, or the 5-minute share as the 1-hour one, is told apart.
MIXED = (
    '{"cache_creation_input_tokens": 1000, "cache_creation":'
    ' {"ephemeral_1h_input_tokens": 600, "ephemeral_5m_input_tokens": 400}}'
)


@dataclass
class _Workspace:
    async def interrupt(self) -> bool:
        return True


async def _stream(line: str) -> AsyncIterator[str]:
    yield line


async def _stored_row_of_one_turn(usage: str) -> TokenUsageData:
    """Feed one assistant turn and return the ``data`` of its TOKEN_USAGE row."""
    writer = AsyncMock()
    collector = ObservabilityCollector(
        writer=writer,
        session_id="session-2145",
        execution_id="exec-2145",
        phase_id="implement",
        workspace_id="ws-2145",
        requested_model=MODEL,
    )
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-2145",
        phase_id="implement",
        session_id="session-2145",
        workspace_id="ws-2145",
        agent_model=MODEL,
        collector=collector,
    )
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg-2145",
                "model": MODEL,
                "content": [{"type": "text", "text": "working"}],
                "usage": json.loads(usage),
            },
        }
    )
    await processor.process_stream(_stream(line), _Workspace())
    rows = [
        call.kwargs["data"]
        for call in writer.record_observation.call_args_list
        if call.kwargs["observation_type"] == ObservationType.TOKEN_USAGE
    ]
    assert len(rows) == 1
    return cast("TokenUsageData", rows[0])


async def test_the_row_stores_the_1h_share_beside_the_unchanged_total() -> None:
    row = await _stored_row_of_one_turn(MIXED)

    assert row["cache_creation_tokens"] == 1000
    assert row["cache_creation_1h_tokens"] == 600


async def test_a_turn_from_an_older_cli_with_no_split_stores_0_1h_writes() -> None:
    row = await _stored_row_of_one_turn('{"cache_creation_input_tokens": 1000}')

    assert row["cache_creation_tokens"] == 1000
    assert row["cache_creation_1h_tokens"] == 0


async def test_a_split_that_disagrees_with_the_total_stores_0_1h_writes() -> None:
    row = await _stored_row_of_one_turn(
        '{"cache_creation_input_tokens": 1000, "cache_creation":'
        ' {"ephemeral_1h_input_tokens": 600, "ephemeral_5m_input_tokens": 600}}'
    )

    assert row["cache_creation_tokens"] == 1000
    assert row["cache_creation_1h_tokens"] == 0
