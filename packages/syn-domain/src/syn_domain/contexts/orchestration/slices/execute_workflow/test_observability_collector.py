"""Unit tests for ObservabilityCollector (ISS-196).

Tests Lane 2 telemetry recording — never touches domain aggregates.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)


def _make_collector(
    writer: Any = None,
) -> ObservabilityCollector:
    """Create a collector with default test values."""
    return ObservabilityCollector(
        writer=writer,
        session_id="sess-1",
        execution_id="exec-1",
        phase_id="phase-1",
        workspace_id="ws-1",
        agent_model="claude-haiku",
    )


@pytest.mark.unit
class TestObservabilityCollectorWithWriter:
    """Tests with an active writer."""

    @pytest.mark.anyio
    async def test_record_hook_event(self) -> None:
        """record_hook_event delegates to writer."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        enriched = {
            "event_type": "tool_execution_started",
            "context": {"tool_name": "Read", "tool_use_id": "t-1"},
            "metadata": {"model": "claude-haiku"},
        }
        await collector.record_hook_event(enriched)

        writer.record_observation.assert_called_once()
        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == "tool_execution_started"
        assert call.kwargs["session_id"] == "sess-1"
        assert call.kwargs["execution_id"] == "exec-1"

    @pytest.mark.anyio
    async def test_record_token_usage(self) -> None:
        """record_token_usage writes TOKEN_USAGE observation."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        await collector.record_token_usage(100, 50, cache_creation=10, cache_read=20)

        writer.record_observation.assert_called_once()
        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == ObservationType.TOKEN_USAGE
        data = call.kwargs["data"]
        assert data["input_tokens"] == 100
        assert data["output_tokens"] == 50
        assert data["cache_creation_tokens"] == 10
        assert data["cache_read_tokens"] == 20
        assert data["model"] == "claude-haiku"

    @pytest.mark.anyio
    async def test_record_tool_started(self) -> None:
        """record_tool_started writes TOOL_EXECUTION_STARTED."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        await collector.record_tool_started("Read", "t-1", '{"file_path": "/foo"}')

        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == ObservationType.TOOL_EXECUTION_STARTED
        assert call.kwargs["data"]["tool_name"] == "Read"

    @pytest.mark.anyio
    async def test_record_tool_completed(self) -> None:
        """record_tool_completed writes TOOL_EXECUTION_COMPLETED."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        await collector.record_tool_completed("Read", "t-1", success=True, output_preview="ok")

        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == ObservationType.TOOL_EXECUTION_COMPLETED
        assert call.kwargs["data"]["success"] is True

    @pytest.mark.anyio
    async def test_record_subagent_started(self) -> None:
        """record_subagent_started writes SUBAGENT_STARTED."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        await collector.record_subagent_started("test-agent", "t-1")

        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == ObservationType.SUBAGENT_STARTED
        assert call.kwargs["data"]["agent_name"] == "test-agent"

    @pytest.mark.anyio
    async def test_record_subagent_stopped(self) -> None:
        """record_subagent_stopped writes SUBAGENT_STOPPED."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        await collector.record_subagent_stopped(
            agent_name="test-agent",
            tool_use_id="t-1",
            duration_ms=500,
            success=True,
            tools_used={"Read": 2, "Edit": 1},
        )

        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == ObservationType.SUBAGENT_STOPPED
        assert call.kwargs["data"]["duration_ms"] == 500

    @pytest.mark.anyio
    async def test_record_embedded_event(self) -> None:
        """record_embedded_event writes arbitrary event type."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        enriched = {
            "context": {"commit_sha": "abc123"},
            "metadata": {"hook": "post-commit"},
        }
        await collector.record_embedded_event("git.commit", enriched)

        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == "git.commit"
        assert call.kwargs["data"]["commit_sha"] == "abc123"


    @pytest.mark.anyio
    async def test_record_session_summary(self) -> None:
        """record_session_summary emits SESSION_SUMMARY with authoritative CLI totals (ISS-217)."""
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        await collector.record_session_summary(
            total_cost_usd=0.0319,
            input_tokens=685,
            output_tokens=1961,
            cache_creation=5596,
            cache_read=144509,
            num_turns=7,
            duration_ms=48000,
        )

        writer.record_observation.assert_called_once()
        call = writer.record_observation.call_args
        assert call.kwargs["observation_type"] == "session_summary"
        assert call.kwargs["session_id"] == "sess-1"
        assert call.kwargs["execution_id"] == "exec-1"
        data = call.kwargs["data"]
        assert data["total_cost_usd"] == pytest.approx(0.0319)
        assert data["total_input_tokens"] == 685
        assert data["total_output_tokens"] == 1961
        assert data["cache_creation_tokens"] == 5596
        assert data["cache_read_tokens"] == 144509
        assert data["num_turns"] == 7
        assert data["duration_ms"] == 48000
        assert data["model"] == "claude-haiku"

    @pytest.mark.anyio
    async def test_record_session_summary_noop_without_writer(self) -> None:
        """record_session_summary is no-op with None writer."""
        collector = _make_collector(writer=None)
        # Must not raise
        await collector.record_session_summary(
            total_cost_usd=0.05,
            input_tokens=100,
            output_tokens=50,
            cache_creation=0,
            cache_read=0,
            num_turns=None,
            duration_ms=None,
        )


@pytest.mark.unit
class TestObservabilityCollectorNullWriter:
    """Tests with None writer — all methods are no-op."""

    @pytest.mark.anyio
    async def test_record_hook_event_noop(self) -> None:
        """record_hook_event is no-op with None writer."""
        collector = _make_collector(writer=None)
        await collector.record_hook_event({"event_type": "test"})
        # No exception = success

    @pytest.mark.anyio
    async def test_record_token_usage_noop(self) -> None:
        """record_token_usage is no-op with None writer."""
        collector = _make_collector(writer=None)
        await collector.record_token_usage(100, 50)

    @pytest.mark.anyio
    async def test_record_tool_started_noop(self) -> None:
        """All record methods are safe with None writer."""
        collector = _make_collector(writer=None)
        await collector.record_tool_started("Read", "t-1", "preview")
        await collector.record_tool_completed("Read", "t-1", True, "output")
        await collector.record_subagent_started("agent", "t-1")
        await collector.record_subagent_stopped("agent", "t-1", 100, True, {"Read": 1})
        await collector.record_embedded_event("test", {"context": {}})

    def test_has_writer_property(self) -> None:
        """has_writer reflects writer presence."""
        assert not _make_collector(writer=None).has_writer
        assert _make_collector(writer=AsyncMock()).has_writer
