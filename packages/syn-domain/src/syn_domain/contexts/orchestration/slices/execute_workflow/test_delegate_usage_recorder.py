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
    seen: list[tuple[str, str, Mapping[str, object]]] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.seen.append((session_id, str(observation_type), dict(data)))


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
    kinds = [k for _, k, _ in writer.seen]
    assert str(ObservationType.TOKEN_USAGE) in kinds
    assert SESSION_SUMMARY in kinds, "without a summary the cost read path never sees this delegate"


async def test_the_summary_carries_a_real_cost() -> None:
    """The number the execution total is built from."""
    writer = await _record(_priced())
    summary = next(d for _, k, d in writer.seen if SESSION_SUMMARY in k)
    assert summary["model"] == "claude-sonnet-5"
    assert summary["total_output_tokens"] == 432
    assert summary["total_cost_usd"] > 0


async def test_an_unpriceable_delegate_gets_a_summary_with_NO_cost() -> None:
    """Tokens still counted, cost absent. That reads as a visible gap rather
    than as work that was free, which is the whole point of not defaulting to
    zero."""
    writer = await _record(None, reason="store does not have it")
    summary = next(d for _, k, d in writer.seen if SESSION_SUMMARY in k)
    assert "total_cost_usd" not in summary
    assert summary["unpriced_reason"]


class TestARefusalLeavesADurableSignal:
    """A log is not a signal (#931 pass 2).

    When the leader cannot be identified nothing is imported - correctly, since
    guessing risks billing the leader twice. But without a durable record the
    phase reports a total that LOOKS complete while captured delegates went
    unpriced, which is the undercount-that-looks-finished this module exists to
    prevent.
    """

    @staticmethod
    async def _refuse(writer: _Writer) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
            import_delegates_for_phase,
        )

        class _Capture:
            agent_session_ids = ("s-a", "s-b")

        class _Store:
            async def fetch_session(self, session_id: str) -> None:
                return None

        await import_delegates_for_phase(
            _Capture(),
            session_store=_Store(),
            writer=writer,
            leader_native_session_id=None,  # never announced -> refusal path
            phase_id="phase-1",
            execution_id="exec-1",
        )

    async def test_the_refusal_records_an_unpriced_marker(self) -> None:
        writer = _Writer()
        await self._refuse(writer)

        assert writer.seen, "the refusal wrote nothing at all - only a log line"
        _, _, data = writer.seen[0]
        assert data["coverage_incomplete"] is True
        assert data["unpriced_reason"]
        assert data["captured_session_count"] == 2

    async def test_the_marker_carries_no_cost(self) -> None:
        """It must report a GAP, never invent spend."""
        writer = _Writer()
        await self._refuse(writer)

        _, _, data = writer.seen[0]
        assert data["model"] is None
        assert data["input_tokens"] == 0
        assert data["output_tokens"] == 0

    async def test_the_marker_id_is_stable_across_attempts(self) -> None:
        """Derived, so a phase reprocessed after a crash addresses the same
        marker instead of accumulating one per attempt."""
        first, second = _Writer(), _Writer()
        await self._refuse(first)
        await self._refuse(second)

        assert first.seen[0][0] == second.seen[0][0]
