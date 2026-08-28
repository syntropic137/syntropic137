"""A delegate needs a session_summary, not just token_usage (#895).

Found on a live run: the delegate's token_usage landed correctly and the
execution total did not move, because ExecutionCostProjection.on_session_summary
is what adds cost - token_usage is only a fallback for sessions still running.
A delegate has no summary of its own, so the import mints one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.agent_sessions.transcript_usage import PricedUsage
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
    DelegateUsageRecorder,
)
from syn_shared.events import SESSION_SUMMARY

pytestmark = pytest.mark.unit


@dataclass
class _Writer:
    seen: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.seen.append((str(observation_type), data))


def _priced() -> PricedUsage:
    return PricedUsage(
        model="claude-sonnet-5",
        uncached_input_tokens=8,
        cache_read_tokens=170756,
        cache_creation_tokens=320,
        output_tokens=432,
        message_count=3,
    )


async def _record(usage: PricedUsage | None, reason: str | None = None) -> _Writer:
    writer = _Writer()
    await DelegateUsageRecorder(writer).record_delegate_usage(
        session_id="child-1",
        usage=usage,
        unpriced_reason=reason,
        execution_id="exec-1",
        phase_id="phase-1",
        workspace_id=None,
    )
    return writer


async def test_both_observations_are_written() -> None:
    writer = await _record(_priced())
    kinds = [k for k, _ in writer.seen]
    assert str(ObservationType.TOKEN_USAGE) in kinds
    assert SESSION_SUMMARY in kinds, "without a summary the cost read path never sees this delegate"


async def test_the_summary_carries_a_real_cost() -> None:
    """The number the execution total is built from."""
    writer = await _record(_priced())
    summary = next(d for k, d in writer.seen if SESSION_SUMMARY in k)
    assert summary["model"] == "claude-sonnet-5"
    assert summary["total_output_tokens"] == 432
    assert summary["total_cost_usd"] > 0


async def test_an_unpriceable_delegate_gets_a_summary_with_NO_cost() -> None:
    """Tokens still counted, cost absent. That reads as a visible gap rather
    than as work that was free, which is the whole point of not defaulting to
    zero."""
    writer = await _record(None, reason="store does not have it")
    summary = next(d for k, d in writer.seen if SESSION_SUMMARY in k)
    assert "total_cost_usd" not in summary
    assert summary["unpriced_reason"]
