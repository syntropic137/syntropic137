"""Tests for EventStreamProcessor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
    _extract_error_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)


async def _lines_to_stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


@dataclass
class MockObservability:
    recordings: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        obs_str = (
            observation_type.value if hasattr(observation_type, "value") else str(observation_type)
        )
        self.recordings.append((obs_str, session_id, data))


@dataclass
class MockWorkspace:
    interrupted: bool = False

    async def interrupt(self) -> bool:
        self.interrupted = True
        return True


def _make_processor(
    tokens: TokenAccumulator | None = None,
    subagents: SubagentTracker | None = None,
    observability: MockObservability | None = None,
) -> EventStreamProcessor:
    return EventStreamProcessor(
        tokens=tokens or TokenAccumulator(),
        subagents=subagents or SubagentTracker(),
        observability=observability,
        controller=None,
        execution_id="exec-1",
        phase_id="phase-1",
        session_id="session-1",
        workspace_id="ws-1",
        agent_model="claude-sonnet",
    )


class TestEventStreamProcessor:
    @pytest.mark.asyncio
    async def test_empty_stream(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(_lines_to_stream(), MockWorkspace())
        assert result.line_count == 0
        assert not result.interrupt_requested
        assert result.agent_task_result is None
        assert result.conversation_lines == []

    @pytest.mark.asyncio
    async def test_result_event_captured_in_stream_result(self) -> None:
        """Result event totals flow into StreamResult — not into TokenAccumulator (ISS-217)."""
        tokens = TokenAccumulator()
        proc = _make_processor(tokens=tokens)
        result_line = json.dumps(
            {
                "type": "result",
                "result": "done",
                "total_cost_usd": 0.0319,
                "duration_ms": 48000,
                "num_turns": 7,
                "usage": {
                    "input_tokens": 685,
                    "output_tokens": 1961,
                    "cache_creation_input_tokens": 5596,
                    "cache_read_input_tokens": 144509,
                },
            }
        )
        result = await proc.process_stream(_lines_to_stream(result_line), MockWorkspace())

        # Authoritative totals in StreamResult
        assert result.result_input_tokens == 685
        assert result.result_output_tokens == 1961
        assert result.result_cache_creation == 5596
        assert result.result_cache_read == 144509
        assert result.total_cost_usd == pytest.approx(0.0319)
        assert result.duration_ms == 48000
        assert result.num_turns == 7
        assert result.line_count == 1

        # Result event is cumulative — must NOT be added to the per-turn accumulator
        assert tokens.input_tokens == 0
        assert tokens.output_tokens == 0

    @pytest.mark.asyncio
    async def test_result_event_does_not_emit_token_usage_observation(self) -> None:
        """Result event must not record a TOKEN_USAGE observation (double-count guard, ISS-217)."""
        obs = MockObservability()
        proc = _make_processor(observability=obs)
        result_line = json.dumps(
            {
                "type": "result",
                "result": "done",
                "total_cost_usd": 0.05,
                "usage": {"input_tokens": 1000, "output_tokens": 200},
            }
        )
        await proc.process_stream(_lines_to_stream(result_line), MockWorkspace())

        token_obs = [r for r in obs.recordings if r[0] == "token_usage"]
        assert len(token_obs) == 0

    @pytest.mark.asyncio
    async def test_per_turn_tokens_not_double_counted(self) -> None:
        """Per-turn assistant tokens accumulate; result event totals don't stack on top (ISS-217)."""
        tokens = TokenAccumulator()
        obs = MockObservability()
        proc = _make_processor(tokens=tokens, observability=obs)

        assistant_line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [],
                    "usage": {"input_tokens": 300, "output_tokens": 80},
                },
            }
        )
        result_line = json.dumps(
            {
                "type": "result",
                "result": "done",
                "total_cost_usd": 0.01,
                # CLI reports cumulative — same numbers in this single-turn case
                "usage": {"input_tokens": 300, "output_tokens": 80},
            }
        )
        result = await proc.process_stream(
            _lines_to_stream(assistant_line, result_line), MockWorkspace()
        )

        # Accumulator only has the per-turn assistant event tokens
        assert tokens.input_tokens == 300
        assert tokens.output_tokens == 80

        # Only one TOKEN_USAGE observation (from assistant event, not the result event)
        token_obs = [r for r in obs.recordings if r[0] == "token_usage"]
        assert len(token_obs) == 1

        # Result totals are in StreamResult
        assert result.result_input_tokens == 300
        assert result.total_cost_usd == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_assistant_event_tokens(self) -> None:
        tokens = TokenAccumulator()
        obs = MockObservability()
        proc = _make_processor(tokens=tokens, observability=obs)
        assistant_line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [],
                    "usage": {"input_tokens": 200, "output_tokens": 50},
                },
            }
        )
        await proc.process_stream(_lines_to_stream(assistant_line), MockWorkspace())
        assert tokens.input_tokens == 200
        assert tokens.output_tokens == 50
        # Should have recorded token usage observation
        token_obs = [r for r in obs.recordings if r[0] == "token_usage"]
        assert len(token_obs) == 1

    @pytest.mark.asyncio
    async def test_tool_use_and_result(self) -> None:
        subagents = SubagentTracker()
        obs = MockObservability()
        proc = _make_processor(subagents=subagents, observability=obs)

        tool_use_line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {}}],
                    "usage": {},
                },
            }
        )
        tool_result_line = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu-1", "content": "file contents"}
                    ],
                },
            }
        )
        await proc.process_stream(
            _lines_to_stream(tool_use_line, tool_result_line), MockWorkspace()
        )
        assert subagents.resolve_tool_name("tu-1") == "Read"
        # Should have tool started and completed observations
        tool_started = [r for r in obs.recordings if r[0] == "tool_execution_started"]
        tool_completed = [r for r in obs.recordings if r[0] == "tool_execution_completed"]
        assert len(tool_started) == 1
        assert len(tool_completed) == 1

    @pytest.mark.asyncio
    async def test_task_result_parsing(self) -> None:
        proc = _make_processor()
        result_line = json.dumps(
            {
                "type": "result",
                "result": 'Done. TASK_RESULT: {"success": true, "comments": "All good"}',
                "usage": {},
            }
        )
        result = await proc.process_stream(_lines_to_stream(result_line), MockWorkspace())
        assert result.agent_task_result is not None
        assert result.agent_task_result["success"] is True
        assert result.agent_task_result["comments"] == "All good"

    @pytest.mark.asyncio
    async def test_conversation_lines_collected(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream("line1", "  ", "line3"), MockWorkspace()
        )
        # Empty/whitespace lines are skipped
        assert result.conversation_lines == ["line1", "line3"]

    @pytest.mark.asyncio
    async def test_non_json_lines_handled(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream("not json at all", "also not json"), MockWorkspace()
        )
        assert result.line_count == 2

    @pytest.mark.asyncio
    async def test_subagent_lifecycle(self) -> None:
        subagents = SubagentTracker()
        obs = MockObservability()
        proc = _make_processor(subagents=subagents, observability=obs)

        # Task tool_use (start subagent)
        task_start = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "task-1",
                            "name": "Task",
                            "input": {"subagent_type": "test-agent"},
                        }
                    ],
                    "usage": {},
                },
            }
        )
        # Task tool_result (stop subagent)
        task_stop = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "task-1", "content": "done"}
                    ],
                },
            }
        )
        await proc.process_stream(_lines_to_stream(task_start, task_stop), MockWorkspace())
        assert not subagents.has_active
        subagent_started = [r for r in obs.recordings if r[0] == "subagent_started"]
        subagent_stopped = [r for r in obs.recordings if r[0] == "subagent_stopped"]
        assert len(subagent_started) == 1
        assert len(subagent_stopped) == 1

    @pytest.mark.asyncio
    async def test_cancel_signal_triggers_interrupt(self) -> None:
        """Test that CANCEL signal from controller triggers interrupt."""
        from dataclasses import dataclass as dc

        @dc
        class FakeSignal:
            signal_type: object
            reason: str

        class FakeSignalType:
            CANCEL = "cancel"

        class FakeController:
            def __init__(self) -> None:
                self.check_count = 0

            async def check_signal(self, execution_id: str) -> FakeSignal | None:
                self.check_count += 1
                # Return cancel on 2nd check (after 20 lines)
                if self.check_count >= 2:
                    return FakeSignal(
                        signal_type=FakeSignalType.CANCEL,
                        reason="user requested",
                    )
                return None

        # Patch ControlSignalType for the import inside the processor
        import syn_adapters.control.commands as ctrl_mod

        original = ctrl_mod.ControlSignalType
        ctrl_mod.ControlSignalType = FakeSignalType  # type: ignore[assignment,misc]

        try:
            controller = FakeController()
            proc = EventStreamProcessor(
                tokens=TokenAccumulator(),
                subagents=SubagentTracker(),
                observability=None,
                controller=controller,  # type: ignore[arg-type]
                execution_id="exec-1",
                phase_id="phase-1",
                session_id="session-1",
                workspace_id=None,
                agent_model="claude",
            )

            # Generate 30 lines — cancel should trigger at line 20
            lines = [f"line-{i}" for i in range(30)]
            ws = MockWorkspace()
            result = await proc.process_stream(_lines_to_stream(*lines), ws)
            assert result.interrupt_requested
            assert result.interrupt_reason == "user requested"
            assert ws.interrupted
            assert result.line_count == 20  # Stopped at line 20
        finally:
            ctrl_mod.ControlSignalType = original


class TestExtractErrorReason:
    """Tests for _extract_error_reason — clean error messages from raw CLI output."""

    def test_anthropic_overloaded_error(self) -> None:
        raw = 'API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"},"request_id":"req_011CZquToahVwgCwb9nCVbPy"}'
        assert _extract_error_reason(raw) == "API overloaded (HTTP 529)"

    def test_anthropic_rate_limit_error(self) -> None:
        raw = 'API Error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"Rate limit exceeded"}}'
        assert _extract_error_reason(raw) == "Rate limited (HTTP 429)"

    def test_anthropic_auth_error(self) -> None:
        raw = 'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid API key"}}'
        assert _extract_error_reason(raw) == "Authentication failed (HTTP 401)"

    def test_anthropic_invalid_request(self) -> None:
        raw = '{"type":"error","error":{"type":"invalid_request_error","message":"max_tokens must be positive"}}'
        assert _extract_error_reason(raw) == "Invalid request: max_tokens must be positive"

    def test_anthropic_500_error(self) -> None:
        raw = 'API Error: 500 {"type":"error","error":{"type":"api_error","message":"Internal server error"}}'
        assert _extract_error_reason(raw) == "API internal error (HTTP 500)"

    def test_plain_text_error(self) -> None:
        assert _extract_error_reason("Connection refused") == "Connection refused"

    def test_empty_string(self) -> None:
        assert _extract_error_reason("") == "Unknown error"

    def test_whitespace_only(self) -> None:
        assert _extract_error_reason("   ") == "Unknown error"

    def test_long_text_truncates_at_word_boundary(self) -> None:
        long_msg = "Error: " + "something went wrong " * 20
        result = _extract_error_reason(long_msg)
        assert len(result) <= 210  # 200 + "..."
        assert result.endswith("...")

    def test_generic_json_with_message(self) -> None:
        raw = '{"message": "Something failed", "code": 42}'
        assert _extract_error_reason(raw) == "Something failed"

    def test_malformed_json_falls_back_to_text(self) -> None:
        raw = 'Error: 529 {"broken json'
        result = _extract_error_reason(raw)
        assert result == 'Error: 529 {"broken json'

    def test_unknown_error_type_uses_type_as_label(self) -> None:
        raw = '{"type":"error","error":{"type":"new_future_error","message":"Something new"}}'
        assert _extract_error_reason(raw) == "new future error: Something new"

    def test_error_type_label_matches_message_no_duplication(self) -> None:
        """When the label and message say the same thing, don't repeat it."""
        raw = '{"type":"error","error":{"type":"overloaded_error","message":"API overloaded"}}'
        assert _extract_error_reason(raw) == "API overloaded"
