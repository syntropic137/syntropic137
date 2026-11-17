"""Tests for EmbeddedEventScanner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.execute_workflow.EmbeddedEventScanner import (
    EmbeddedEventScanner,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)


@dataclass
class MockCollector:
    """Mock ObservabilityCollector that records embedded events."""

    embedded_events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def record_embedded_event(self, event_type: str, enriched: dict[str, Any]) -> None:
        self.embedded_events.append((event_type, enriched))


def _make_scanner(collector: MockCollector | None = None) -> EmbeddedEventScanner:
    return EmbeddedEventScanner(
        collector=collector or MockCollector(),  # type: ignore[arg-type]
        execution_id="exec-1",
        phase_id="phase-1",
    )


@pytest.mark.unit
class TestEmbeddedEventScanner:
    @pytest.mark.asyncio
    async def test_valid_embedded_jsonl_recorded(self) -> None:
        collector = MockCollector()
        scanner = _make_scanner(collector)  # type: ignore[arg-type]
        # Use a known valid event type from the system
        content = json.dumps({"event_type": "git_commit", "session_id": "s-1", "timestamp": "t1"})
        await scanner.scan_and_record(content, "Bash")
        assert len(collector.embedded_events) == 1
        assert collector.embedded_events[0][0] == "git_commit"

    @pytest.mark.asyncio
    async def test_invalid_event_type_skipped(self) -> None:
        collector = MockCollector()
        scanner = _make_scanner(collector)  # type: ignore[arg-type]
        content = json.dumps({"event_type": "totally_bogus_type", "session_id": "s-1"})
        await scanner.scan_and_record(content, "Bash")
        assert len(collector.embedded_events) == 0

    @pytest.mark.asyncio
    async def test_non_jsonl_lines_ignored(self) -> None:
        collector = MockCollector()
        scanner = _make_scanner(collector)  # type: ignore[arg-type]
        content = "regular text output\nnot json\n"
        await scanner.scan_and_record(content, "Read")
        assert len(collector.embedded_events) == 0

    @pytest.mark.asyncio
    async def test_empty_content_is_noop(self) -> None:
        collector = MockCollector()
        scanner = _make_scanner(collector)  # type: ignore[arg-type]
        await scanner.scan_and_record("", "Read")
        assert len(collector.embedded_events) == 0

    @pytest.mark.asyncio
    async def test_mixed_content_only_records_valid(self) -> None:
        collector = MockCollector()
        scanner = _make_scanner(collector)  # type: ignore[arg-type]
        valid = json.dumps({"event_type": "git_merge", "session_id": "s-1", "timestamp": "t1"})
        content = f"regular output\n{valid}\nmore text\n"
        await scanner.scan_and_record(content, "Bash")
        assert len(collector.embedded_events) == 1


@dataclass
class _Observation:
    session_id: str
    observation_type: str
    data: dict[str, Any]
    execution_id: str | None


@dataclass
class _RecordingWriter:
    """What reaches the observation store: the rows the cost read path sums."""

    rows: list[_Observation] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.rows.append(_Observation(session_id, str(observation_type), data, execution_id))


@dataclass
class _Pushes:
    seen: list[tuple[str, str, str]] = field(default_factory=list)

    async def __call__(self, repository: str, branch: str, sha: str) -> None:
        self.seen.append((repository, branch, sha))


_PUSH_SHA = "1234567abcdef1234567abcdef1234567abcdef0"
_ORIGIN = "https://github.com/acme/widgets.git"


def _delegate_tool_output() -> str:
    """A delegated command's output: the child's own cost lines, then a real push.

    The child's ``session_summary`` and ``token_usage`` are valid event types
    but are not the leader's spend; the delegate is priced from its transcript.
    """
    child_summary = {
        "event_type": "session_summary",
        "session_id": "child-sess",
        "timestamp": "2026-11-17T01:00:00+00:00",
        "context": {"total_cost_usd": 0.25, "total_input_tokens": 1000, "total_output_tokens": 500},
    }
    child_tokens = {
        "event_type": "token_usage",
        "session_id": "child-sess",
        "timestamp": "2026-11-17T01:00:00+00:00",
        "context": {"input_tokens": 1000, "output_tokens": 500},
    }
    push = {
        "event_type": "git_push",
        "session_id": "child-sess",
        "timestamp": "2026-11-17T01:00:01+00:00",
        "context": {
            "git": {
                "operation": "push",
                "remote": "origin",
                "branch": "feat/x",
                "sha": _PUSH_SHA,
                "repo": "widgets",
                "remote_url": _ORIGIN,
            }
        },
    }
    return "\n".join(
        [
            json.dumps(child_summary),
            json.dumps(child_tokens),
            json.dumps(push),
            f"To {_ORIGIN}",
            f"   abcdef0..{_PUSH_SHA[:7]}  feat/x -> feat/x",
        ]
    )


async def _scan_leader_tool_output() -> tuple[_RecordingWriter, _Pushes]:
    writer = _RecordingWriter()
    pushes = _Pushes()
    collector = ObservabilityCollector(
        writer=writer,
        session_id="leader-sess",
        execution_id="exec-935",
        phase_id="phase-1",
        workspace_id="ws-1",
        requested_model="opus",
    )
    scanner = EmbeddedEventScanner(collector, "exec-935", "phase-1", on_push=pushes)
    await scanner.scan_and_record(_delegate_tool_output(), "Bash")
    return writer, pushes


@pytest.mark.unit
class TestToolOutputIsNotBilling:
    """#935: cost lines a tool prints are not recorded as the leader's spend."""

    @pytest.mark.asyncio
    async def test_embedded_cost_events_record_nothing(self) -> None:
        writer, _ = await _scan_leader_tool_output()
        assert [row.observation_type for row in writer.rows] == ["git_push"]

    @pytest.mark.asyncio
    async def test_git_hook_event_beside_them_is_still_observed_as_a_push(self) -> None:
        writer, pushes = await _scan_leader_tool_output()
        assert writer.rows[0].session_id == "leader-sess"
        assert pushes.seen == [("widgets", "feat/x", _PUSH_SHA)]

    @pytest.mark.asyncio
    async def test_execution_totals_count_the_delegate_once(self) -> None:
        """Leader $1.00 + delegate transcript $0.25 = $1.25, not $1.50."""
        projection = ExecutionCostProjection(InMemoryProjectionStore())
        leader_summary = {"total_cost_usd": 1.00, "total_input_tokens": 4000}
        delegate_import = {"total_cost_usd": 0.25, "total_input_tokens": 1000}
        await projection.on_session_summary(
            {"execution_id": "exec-935", "session_id": "leader-sess", "data": leader_summary}
        )
        await projection.on_session_summary(
            {"execution_id": "exec-935", "session_id": "delegate-sess", "data": delegate_import}
        )

        writer, _ = await _scan_leader_tool_output()
        for row in writer.rows:
            event = {
                "execution_id": row.execution_id,
                "session_id": row.session_id,
                "observation_type": row.observation_type,
                "data": row.data,
            }
            if row.observation_type == "session_summary":
                await projection.on_session_summary(event)
            else:
                await projection.on_agent_observation(event)

        cost = await projection.get_execution_cost("exec-935")
        assert cost is not None
        assert cost.total_cost_usd == Decimal("1.25")
        assert cost.input_tokens == 5000
