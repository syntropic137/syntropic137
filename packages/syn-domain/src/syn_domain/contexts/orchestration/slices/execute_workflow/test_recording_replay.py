"""Recording-based replay tests for EventStreamProcessor.

Replays real recordings through the full EventStreamProcessor pipeline,
validating token accumulation, tool tracking, subagent lifecycle, and
observability across CLI versions.

ZERO TOKEN COST — uses pre-recorded agent sessions.

See ADR-033: Recording-Based Integration Testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from agentic_events import Recording

from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

pytestmark = [pytest.mark.unit, pytest.mark.integration]


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_event_stream_processor.py)
# ---------------------------------------------------------------------------


@dataclass
class MockObservability:
    recordings: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: Any,  # noqa: ANN401
        data: dict[str, Any],
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


_FAKE_HANDLE = IsolationHandle(
    isolation_id="recording-test",
    isolation_type="recording",
    proxy_url=None,
    workspace_path="/workspace",
)


def _make_processor(
    session_id: str = "session-1",
    tokens: TokenAccumulator | None = None,
    subagents: SubagentTracker | None = None,
    observability: MockObservability | None = None,
) -> EventStreamProcessor:
    return EventStreamProcessor(
        tokens=tokens or TokenAccumulator(),
        subagents=subagents or SubagentTracker(),
        observability=observability,
        controller=None,
        execution_id="exec-recording",
        phase_id="phase-recording",
        session_id=session_id,
        workspace_id="ws-recording",
        agent_model="claude-sonnet",
    )


async def _replay_recording(
    recording: Recording | str,
    *,
    observability: MockObservability | None = None,
    tokens: TokenAccumulator | None = None,
    subagents: SubagentTracker | None = None,
) -> tuple[StreamResult, MockObservability, TokenAccumulator, SubagentTracker]:
    """Replay a recording through EventStreamProcessor.

    Returns (result, observability, tokens, subagents) for assertions.
    """
    adapter = RecordingEventStreamAdapter(recording)
    obs = observability or MockObservability()
    tok = tokens or TokenAccumulator()
    sub = subagents or SubagentTracker()

    session_id = adapter.session_id or "unknown-session"
    proc = _make_processor(session_id=session_id, tokens=tok, subagents=sub, observability=obs)

    result = await proc.process_stream(
        adapter.stream(_FAKE_HANDLE, []),
        MockWorkspace(),
    )
    return result, obs, tok, sub


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestRecordingReplay:
    """Replay real recordings through EventStreamProcessor."""

    @pytest.mark.asyncio
    async def test_simple_bash_token_accumulation(self) -> None:
        """SIMPLE_BASH recording accumulates tokens through the processor."""
        result, _obs, tokens, _sub = await _replay_recording(Recording.SIMPLE_BASH)

        assert result.line_count > 0
        assert tokens.input_tokens > 0, "Expected input tokens from recording"
        assert tokens.output_tokens > 0, "Expected output tokens from recording"
        assert result.line_count == RecordingEventStreamAdapter(Recording.SIMPLE_BASH).event_count

    @pytest.mark.asyncio
    async def test_multi_tool_observability(self) -> None:
        """MULTI_TOOL recording produces tool start/complete observations."""
        result, obs, _tok, _sub = await _replay_recording(Recording.MULTI_TOOL)

        assert result.line_count > 0

        tool_started = [r for r in obs.recordings if r[0] == "tool_execution_started"]
        tool_completed = [r for r in obs.recordings if r[0] == "tool_execution_completed"]

        assert len(tool_started) > 0, "Expected tool_execution_started observations"
        assert len(tool_completed) > 0, "Expected tool_execution_completed observations"

        # Multiple distinct tools used
        tool_names = {r[2].get("tool_name") for r in tool_started}
        assert len(tool_names) >= 2, f"Expected multiple tool names, got {tool_names}"

    @pytest.mark.asyncio
    async def test_simple_question_no_tools(self) -> None:
        """SIMPLE_QUESTION recording: tokens but no tool observations."""
        result, obs, tokens, _sub = await _replay_recording(Recording.SIMPLE_QUESTION)

        assert result.line_count > 0
        assert tokens.input_tokens > 0 or tokens.output_tokens > 0

        tool_obs = [
            r
            for r in obs.recordings
            if r[0] in ("tool_execution_started", "tool_execution_completed")
        ]
        assert len(tool_obs) == 0, f"Expected no tool observations, got {len(tool_obs)}"

    @pytest.mark.asyncio
    async def test_file_operations_tool_tracking(self) -> None:
        """FILE_CREATE recording tracks write tool lifecycle."""
        result, obs, _tok, _sub = await _replay_recording(Recording.FILE_CREATE)

        assert result.line_count > 0

        tool_started = [r for r in obs.recordings if r[0] == "tool_execution_started"]
        tool_completed = [r for r in obs.recordings if r[0] == "tool_execution_completed"]

        assert len(tool_started) > 0, "Expected tool start observations"
        assert len(tool_completed) > 0, "Expected tool completion observations"

        # Should see a Write tool
        tool_names = {r[2].get("tool_name") for r in tool_started}
        assert any("Write" in name or "write" in name for name in tool_names if name), (
            f"Expected Write tool, got {tool_names}"
        )

    @pytest.mark.asyncio
    async def test_subagent_concurrent_lifecycle(self) -> None:
        """SUBAGENT_CONCURRENT recording: subagent start/stop tracked."""
        result, obs, _tok, subagents = await _replay_recording(Recording.SUBAGENT_CONCURRENT)

        assert result.line_count > 0

        subagent_started = [r for r in obs.recordings if r[0] == "subagent_started"]
        subagent_stopped = [r for r in obs.recordings if r[0] == "subagent_stopped"]

        assert len(subagent_started) > 0, "Expected subagent_started observations"
        assert len(subagent_stopped) > 0, "Expected subagent_stopped observations"
        assert not subagents.has_active, "All subagents should be stopped after replay"

    @pytest.mark.asyncio
    async def test_context_tracking_hook_events(self) -> None:
        """CONTEXT_TRACKING recording: v2.1.29 hook events parsed and recorded."""
        result, obs, _tok, _sub = await _replay_recording(Recording.CONTEXT_TRACKING)

        assert result.line_count > 0

        # Hook events should produce observations (tool tracking via hooks)
        assert len(obs.recordings) > 0, "Expected observations from hook events"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("recording", list(Recording))
    async def test_all_recordings_smoke(self, recording: Recording) -> None:
        """SMOKE: Every recording replays without errors, has valid metadata."""
        try:
            adapter = RecordingEventStreamAdapter(recording)
        except FileNotFoundError:
            pytest.skip(f"{recording.value} recording not available")

        # Version awareness: every recording must have cli_version in metadata
        metadata = adapter.metadata
        assert metadata is not None, f"{recording.value}: no metadata"
        assert metadata.cli_version, f"{recording.value}: empty cli_version"

        result, _obs, _tok, _sub = await _replay_recording(recording)

        assert result.line_count > 0, f"{recording.value}: no lines processed"
