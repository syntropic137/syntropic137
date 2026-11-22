"""#2145 slice B1: a live claude turn's 1-hour cache writes are priced at the 1-hour rate.

Claude's per-turn usage carries the cache-write total in
``cache_creation_input_tokens`` and its split by TTL in
``cache_creation.ephemeral_{1h,5m}_input_tokens``. The phase cost limiter read
only the total, so a 1-hour write was charged at the 5-minute rate: $5.00
instead of $8.00 per million on Opus 5.5, and a phase overspent its
``max_cost_usd``. These drive a real turn through the stream processor and
read what the limiter CONSUMED, which is the hop that spends the money.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
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
from syn_shared.agents import ModelId

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

MODEL = ModelId.CLAUDE_OPUS_5_5.value
MILLION = 1_000_000
#: One million cache-write tokens, every one of them a 1-hour write - the shape
#: of the recorded turns in tests/fixtures/delegation/claude_transcript_usage.jsonl.
ALL_1H = (
    '{"cache_creation_input_tokens": 1000000, "cache_creation":'
    ' {"ephemeral_1h_input_tokens": 1000000, "ephemeral_5m_input_tokens": 0}}'
)


@dataclass
class _Workspace:
    async def interrupt(self) -> bool:
        return True


async def _stream(line: str) -> AsyncIterator[str]:
    yield line


async def _spent_on_one_turn(usage: str) -> tuple[Decimal, TokenAccumulator]:
    """Feed one assistant turn whose ``usage`` is the given JSON object text."""
    limit = PhaseCostLimit(max_cost_usd=1_000.0)
    tokens = TokenAccumulator()
    processor = EventStreamProcessor(
        tokens=tokens,
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-2145",
        phase_id="implement",
        session_id="session-2145",
        workspace_id="ws-2145",
        agent_model=MODEL,
        cost_limit=limit,
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
    return limit.spent_usd, tokens


async def test_a_1h_cache_write_is_priced_at_the_1h_rate() -> None:
    spent, _ = await _spent_on_one_turn(ALL_1H)

    assert spent == Decimal("8.00")


async def test_a_turn_from_an_older_cli_with_no_split_is_all_5_minute() -> None:
    spent, _ = await _spent_on_one_turn('{"cache_creation_input_tokens": 1000000}')

    assert spent == Decimal("5.00")


async def test_a_mixed_turn_prices_each_tier_at_its_own_rate() -> None:
    spent, _ = await _spent_on_one_turn(
        '{"cache_creation_input_tokens": 3000000, "cache_creation":'
        ' {"ephemeral_1h_input_tokens": 1000000, "ephemeral_5m_input_tokens": 2000000}}'
    )

    # 2M x $5.00 (5-minute) + 1M x $8.00 (1-hour).
    assert spent == Decimal("18.00")


@pytest.mark.parametrize(
    "split",
    [
        # More 1-hour writes than writes in total.
        '{"ephemeral_1h_input_tokens": 2000000, "ephemeral_5m_input_tokens": 0}',
        # The two tiers do not add up to the total.
        '{"ephemeral_1h_input_tokens": 1000000, "ephemeral_5m_input_tokens": 1000000}',
        '{"ephemeral_1h_input_tokens": -1}',
        '{"ephemeral_1h_input_tokens": "lots"}',
        '"not-an-object"',
    ],
    ids=["1h-exceeds-total", "tiers-overcount", "negative", "not-a-number", "not-an-object"],
)
async def test_a_split_that_disagrees_with_the_total_is_priced_as_today(split: str) -> None:
    spent, _ = await _spent_on_one_turn(
        f'{{"cache_creation_input_tokens": 1000000, "cache_creation": {split}}}'
    )

    assert spent == Decimal("5.00")


async def test_the_recorded_token_total_still_counts_every_cache_write() -> None:
    """Stored counts are unchanged in B1: the total, not the 5-minute share."""
    _, tokens = await _spent_on_one_turn(ALL_1H)

    assert tokens.cache_creation_tokens == MILLION


@pytest.mark.unit
@pytest.mark.parametrize(
    "usage_json",
    [
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": true, "ephemeral_5m_input_tokens": 99}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": 1, "ephemeral_5m_input_tokens": 99.0}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": 99, "ephemeral_5m_input_tokens": true}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": 40.0}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": -1}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": 101}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": 60, "ephemeral_5m_input_tokens": 30}}',
        '{"cache_creation_input_tokens": 100, "cache_creation": [60, 40]}',
        '{"cache_creation_input_tokens": true, "cache_creation": {"ephemeral_1h_input_tokens": 1}}',
    ],
    ids=[
        "1h-bool",
        "5m-float",
        "5m-bool",
        "1h-float",
        "1h-negative",
        "1h-over-total",
        "5m-disagrees",
        "split-not-mapping",
        "total-bool",
    ],
)
def test_a_malformed_split_is_priced_as_it_was_before(usage_json: str) -> None:
    """Anything but real non-negative int counts that add up is today's pricing: no 1-hour share.

    The cases are JSON text because that is what the stream delivers: ``true``
    and ``99.0`` arrive as ``bool`` and ``float``, which compare equal to ints.
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        cache_writes_from_claude_usage,
    )

    usage = json.loads(usage_json)
    writes = cache_writes_from_claude_usage(usage)

    assert writes.one_hour == 0
    assert writes.five_minute is usage["cache_creation_input_tokens"]
