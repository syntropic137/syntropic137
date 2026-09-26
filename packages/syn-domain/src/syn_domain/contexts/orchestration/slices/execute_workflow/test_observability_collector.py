"""Unit tests for ObservabilityCollector (ISS-196).

Tests Lane 2 telemetry recording — never touches domain aggregates.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)


def _make_collector(
    writer: AsyncMock | None = None,
) -> ObservabilityCollector:
    """Create a collector with default test values."""
    return ObservabilityCollector(
        writer=writer,
        session_id="sess-1",
        execution_id="exec-1",
        phase_id="phase-1",
        workspace_id="ws-1",
        requested_model="claude-haiku",
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
        # Nothing reported a model, so the row says unknown; the request is
        # carried separately and never as `model` (ADR-067).
        assert data["model"] is None
        assert data["requested_model"] == "claude-haiku"

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
    async def test_record_embedded_event_renames_message(self) -> None:
        """record_embedded_event renames 'message' to 'commit_message'.

        'message' is a RESERVED_OBSERVATION_KEYS entry that would be silently
        stripped by record_observation. Git hooks emit commit messages as the
        plain string field 'message', so we rename to 'commit_message' to
        preserve it through the pipeline.
        """
        writer = AsyncMock()
        collector = _make_collector(writer=writer)

        enriched = {
            "context": {
                "operation": "commit",
                "message": "feat: add MIT license",
                "sha": "abc123",
                "branch": "main",
            },
            "metadata": {"repo": "my-repo"},
        }
        await collector.record_embedded_event("git_commit", enriched)

        call = writer.record_observation.call_args
        data = call.kwargs["data"]
        assert "message" not in data, "message should be renamed to avoid reserved-key stripping"
        assert data["commit_message"] == "feat: add MIT license"
        assert data["sha"] == "abc123"
        assert data["repo"] == "my-repo"

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
        assert data["model"] is None
        assert data["requested_model"] == "claude-haiku"

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


@pytest.mark.unit
class TestSawAgentActivity:
    """The one witness that a phase's agent actually did something (#1303).

    Retrying a busy upstream is only safe for a launch that never started, and
    this flag is how that is known. Whether it is set decides whether a failed
    phase is re-run, so each way of reaching it needs its own test - a path
    that stops setting it would otherwise cost a duplicated phase, silently.

    The list below is the point of the fact rather than an inventory of it. It
    started as tool starts and completions alone, under the name
    `saw_tool_use`, and every entry added since was a path an agent really took
    and this collector really called "nothing happened": a hook-delivered tool
    call, a subagent, a git commit scanned out of tool output.
    """

    def test_a_fresh_collector_has_seen_nothing(self) -> None:
        assert not _make_collector(writer=AsyncMock()).saw_agent_activity

    @pytest.mark.anyio
    async def test_a_started_tool_is_activity(self) -> None:
        collector = _make_collector(writer=AsyncMock())

        await collector.record_tool_started("Bash", "t-1", "rm -rf build")

        assert collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_a_completed_tool_is_activity_even_with_no_start_behind_it(self) -> None:
        """Codex can announce a `file_change` only on completion (#1064).

        Counting starts alone would miss the tool op that already edited the
        workspace, and the phase would be re-run over its own edits.
        """
        collector = _make_collector(writer=AsyncMock())

        await collector.record_tool_completed("file_change", "t-1", success=True, output_preview="")

        assert collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_a_hook_event_is_activity(self) -> None:
        """Claude reports some tool calls ONLY through the hook channel.

        Those never reach `record_tool_started`, so while this method was the
        one recorder that set nothing, a phase whose every tool call arrived
        this way was indistinguishable from a phase that never started - and
        was re-run over the edits, commits and pushes those calls had made.
        """
        collector = _make_collector(writer=AsyncMock())

        await collector.record_hook_event(
            {"event_type": "tool_execution_started", "context": {"tool_name": "Bash"}}
        )

        assert collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_a_subagent_is_activity(self) -> None:
        """A subagent is a whole agent run. A phase that started one has not
        "never started", whether or not the parent `Task` event survived."""
        collector = _make_collector(writer=AsyncMock())

        await collector.record_subagent_started("reviewer", "t-1")

        assert collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_an_embedded_git_event_is_activity(self) -> None:
        """Scanned out of a tool's OUTPUT, so the commit already happened."""
        collector = _make_collector(writer=AsyncMock())

        await collector.record_embedded_event(
            "git_commit", {"context": {"git": {"sha": "abc1234"}}}
        )

        assert collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_a_bare_note_is_activity(self) -> None:
        """The stream processors' entry point, for the events with nothing
        worth recording: a thinking-only turn, an unrecognised content block,
        a codex item type this parser has never seen. No observation to store,
        and still proof the model started."""
        collector = _make_collector(writer=AsyncMock())

        collector.note_agent_activity()

        assert collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_spending_tokens_alone_is_not_activity(self) -> None:
        """The deliberate exclusion, and the one that keeps the retry possible.

        A request that reached the model and was refused for capacity can carry
        input tokens. That is a bill, not work to preserve - count it and the
        busy-upstream retry #1303 exists for never fires at all.
        """
        collector = _make_collector(writer=AsyncMock())

        await collector.record_token_usage(input_tokens=1200, output_tokens=0)

        assert not collector.saw_agent_activity

    @pytest.mark.anyio
    async def test_activity_is_witnessed_with_no_writer_to_record_it(self) -> None:
        """The flag is about what the AGENT did, not about who stored it.

        A collector with no writer still runs a real agent against a real
        workspace. Reading "no work" off a missing writer would make every such
        phase retriable.
        """
        collector = _make_collector(writer=None)

        await collector.record_tool_started("Bash", "t-1", "")

        assert collector.saw_agent_activity
