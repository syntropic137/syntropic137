"""Tests for CodexStreamProcessor.

Uses the golden real-captured fixture
(``packages/syn-domain/tests/fixtures/codex/codex_exec_recording.jsonl``),
plus two hand-crafted failure fixtures. The golden fixture is a SINGLE-turn
recording (one ``turn.completed``); no real multi-turn ``codex exec --json``
capture was available in this environment, so cross-turn summation is not
exercised end-to-end here. If a real multi-turn recording becomes available,
add a ``test_multi_turn_sums_across_turns`` case that asserts summed totals
equal the sum of each turn's fresh_input/output/cache_read.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "codex"


@dataclass
class _RecordingCollector:
    calls: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def record_tool_started(self, **kwargs: object) -> None:
        self.calls.append(("tool_started", kwargs))

    async def record_tool_completed(self, **kwargs: object) -> None:
        self.calls.append(("tool_completed", kwargs))

    async def record_token_usage(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("token_usage", {"args": args, **kwargs}))

    async def record_session_summary(self, **kwargs: object) -> None:
        self.calls.append(("summary", kwargs))


class _NoopWorkspace:
    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


async def _lines(path: Path) -> AsyncIterator[str]:
    for line in path.read_text().splitlines():
        yield line


def _make_processor(
    collector: _RecordingCollector, agent_model: str | None = "gpt-5.6"
) -> tuple[CodexStreamProcessor, TokenAccumulator]:
    tokens = TokenAccumulator()
    processor = CodexStreamProcessor(
        tokens=tokens,
        collector=collector,
        controller=None,
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model=agent_model,
    )
    return processor, tokens


@pytest.mark.asyncio
async def test_codex_recording_produces_timeline() -> None:
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    kinds = [c[0] for c in collector.calls]
    assert "tool_started" in kinds
    assert "tool_completed" in kinds
    assert "token_usage" in kinds

    summary = next(c[1] for c in collector.calls if c[0] == "summary")
    assert summary["input_tokens"] > 0
    assert summary["output_tokens"] > 0
    assert summary["total_cost_usd"] is not None
    assert summary["total_cost_usd"] > 0

    # Fixture: input_tokens=97006, cached_input_tokens=87808, output_tokens=288,
    # reasoning_output_tokens=0 => fresh_input=9198, cache_read=87808, output=288.
    assert result.result_input_tokens == 9198
    assert result.result_cache_read == 87808
    assert result.result_output_tokens == 288
    assert result.num_turns == 1
    assert result.error_reason is None

    # Shared TokenAccumulator updated too (not just StreamResult.result_*).
    assert tokens.input_tokens == result.result_input_tokens
    assert tokens.output_tokens == result.result_output_tokens
    assert tokens.cache_read_tokens == result.result_cache_read

    # Raw provider-native JSONL preserved, including interleaved non-JSON
    # noise lines the real codex CLI emits on stdout.
    assert result.conversation_lines
    assert any("turn.completed" in line for line in result.conversation_lines)


@pytest.mark.asyncio
async def test_command_execution_tool_pair_recorded() -> None:
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    await processor.process_stream(_lines(rec), _NoopWorkspace())

    started = [c[1] for c in collector.calls if c[0] == "tool_started"]
    completed = [c[1] for c in collector.calls if c[0] == "tool_completed"]

    bash_started = [c for c in started if c["tool_name"] == "Bash"]
    bash_completed = [c for c in completed if c["tool_name"] == "Bash"]
    assert len(bash_started) == 2  # item_2 ('cat one.txt'), item_4 ('ls -1')
    assert len(bash_completed) == 2
    assert all(c["success"] is True for c in bash_completed)
    assert bash_started[0]["input_preview"] == "/bin/zsh -lc 'cat one.txt'"
    assert bash_completed[0]["output_preview"] == "alpha\n"

    edit_started = [c for c in started if c["tool_name"] == "Edit"]
    edit_completed = [c for c in completed if c["tool_name"] == "Edit"]
    assert len(edit_started) == 2  # item_1 (one.txt), item_3 (two.txt)
    assert len(edit_completed) == 2
    assert all(c["success"] is True for c in edit_completed)

    # #1064: a command_execution has a real item.started/item.completed pair
    # on the wire, so it gets a duration key; a file_change item.completed
    # arrives with no matching started event (its "start" is synthesized
    # inline), so it must report None rather than a near-zero stand-in.
    # `c["duration_ms"]` (not `.get`) so this fails with KeyError, not a
    # silent pass, against the pre-fix collector that never wrote the key.
    assert all(c["duration_ms"] is not None for c in bash_completed)
    assert all(c["duration_ms"] is None for c in edit_completed)


@pytest.mark.asyncio
async def test_command_execution_duration_ms_measures_elapsed_time() -> None:
    """duration_ms reflects the real gap between item.started and item.completed (#1064).

    The 15ms floor is well below the injected asyncio.sleep(0.03) but could
    not be produced by a hardcoded stand-in value.
    """
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    started_event = json.dumps(
        {
            "type": "item.started",
            "item": {"id": "cmd-1", "type": "command_execution", "command": "echo hi"},
        }
    )
    completed_event = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "cmd-1",
                "type": "command_execution",
                "command": "echo hi",
                "aggregated_output": "hi\n",
                "exit_code": 0,
            },
        }
    )
    turn_completed_event = json.dumps(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5},
        }
    )

    async def _delayed_stream() -> AsyncIterator[str]:
        yield started_event
        await asyncio.sleep(0.03)
        yield completed_event
        yield turn_completed_event

    await processor.process_stream(_delayed_stream(), _NoopWorkspace())

    completed = [c[1] for c in collector.calls if c[0] == "tool_completed"]
    assert len(completed) == 1
    duration_ms = completed[0]["duration_ms"]
    assert duration_ms is not None
    assert duration_ms >= 15


@pytest.mark.asyncio
async def test_command_execution_completed_without_started_has_no_duration() -> None:
    """A truncated stream (completed with no matching started) yields None, not 0 (#1064)."""
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    completed_event = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "cmd-orphan",
                "type": "command_execution",
                "command": "echo hi",
                "aggregated_output": "hi\n",
                "exit_code": 0,
            },
        }
    )
    turn_completed_event = json.dumps(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
        }
    )

    async def _stream() -> AsyncIterator[str]:
        yield completed_event
        yield turn_completed_event

    await processor.process_stream(_stream(), _NoopWorkspace())

    completed = [c[1] for c in collector.calls if c[0] == "tool_completed"]
    assert len(completed) == 1
    assert completed[0]["duration_ms"] is None


@pytest.mark.asyncio
async def test_malformed_json_fails_explicitly() -> None:
    rec = _FIXTURES_DIR / "codex_malformed.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is not None
    assert "malformed" in result.error_reason


@pytest.mark.asyncio
async def test_no_terminal_usage_fails_explicitly() -> None:
    rec = _FIXTURES_DIR / "codex_no_terminal.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is not None
    assert "turn.completed" in result.error_reason
    assert result.num_turns == 0


@pytest.mark.asyncio
async def test_empty_stream_fails_explicitly() -> None:
    async def _empty() -> AsyncIterator[str]:
        return
        yield  # pragma: no cover - makes this an async generator

    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_empty(), _NoopWorkspace())

    assert result.error_reason is not None
    assert result.line_count == 0
    # A session summary is still emitted exactly once (single-layer emission
    # guarantee), just with zeroed totals and cost unavailable if the model
    # can't be priced from zero tokens... it CAN be priced (0 * rate == 0),
    # so total_cost_usd is 0.0 for a known model on an empty stream.
    summaries = [c for c in collector.calls if c[0] == "summary"]
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_unknown_model_marks_cost_unavailable() -> None:
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector, agent_model="mystery-model")

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.total_cost_usd is None
    summary = next(c[1] for c in collector.calls if c[0] == "summary")
    assert summary["total_cost_usd"] is None


@pytest.mark.asyncio
async def test_none_model_marks_cost_unavailable_not_haiku_not_gpt_5_6() -> None:
    """A codex phase with no explicit model (agent_model=None) must NOT be
    priced at all - specifically not claude haiku rates (the original #788
    bug) and not GPT-5.6 rates (the #788 fix's over-correction, which
    synthesized "codex" as the model and let it alias to gpt-5.6 pricing).
    Cost must resolve to unknown/unpriced (None).
    """
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector, agent_model=None)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.total_cost_usd is None
    summary = next(c[1] for c in collector.calls if c[0] == "summary")
    assert summary["total_cost_usd"] is None


@pytest.mark.asyncio
async def test_cancel_signal_interrupts() -> None:
    from syn_adapters.control.commands import ControlSignalType

    class _SpyWorkspace:
        last_stream_exit_code = 0

        def __init__(self) -> None:
            self.interrupted = False

        async def interrupt(self) -> bool:
            self.interrupted = True
            return True

    class _Signal:
        signal_type = ControlSignalType.CANCEL
        reason = "user requested stop"

    class _FakeController:
        async def check_signal(self, execution_id: str) -> _Signal:
            return _Signal()

    async def _many_lines() -> AsyncIterator[str]:
        for _ in range(11):
            yield '{"type":"turn.started"}'

    collector = _RecordingCollector()
    tokens = TokenAccumulator()
    processor = CodexStreamProcessor(
        tokens=tokens,
        collector=collector,
        controller=_FakeController(),  # type: ignore[arg-type]
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model="gpt-5.6",
    )
    workspace = _SpyWorkspace()

    result = await processor.process_stream(_many_lines(), workspace)

    assert workspace.interrupted is True
    assert result.interrupt_requested is True
    assert result.interrupt_reason == "user requested stop"


@pytest.mark.asyncio
async def test_cancel_with_no_reason_still_interrupts() -> None:
    """#918: a cancel with no reason text is still a cancel, codex side.

    ``test_cancel_signal_interrupts`` above sends ``reason="user requested
    stop"`` and passes both before and after the fix, because
    ``interrupt_requested`` used to be derived as ``interrupt_reason is not
    None``. The default CLI path - ``syn control cancel <id> --force`` with no
    ``-r`` - sends no reason at all, so the flag evaluated False and the
    workflow continued to its remaining phases.
    """
    from syn_shared.control import ControlSignalType

    class _SpyWorkspace:
        last_stream_exit_code = 0

        def __init__(self) -> None:
            self.interrupted = False

        async def interrupt(self) -> bool:
            self.interrupted = True
            return True

    class _Signal:
        signal_type = ControlSignalType.CANCEL
        reason = None  # what the CLI actually sends without -r

    class _FakeController:
        async def check_signal(self, execution_id: str) -> _Signal:
            return _Signal()

    async def _many_lines() -> AsyncIterator[str]:
        for _ in range(11):
            yield '{"type":"turn.started"}'

    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_RecordingCollector(),
        controller=_FakeController(),  # type: ignore[arg-type]
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model="gpt-5.6",
    )
    workspace = _SpyWorkspace()

    result = await processor.process_stream(_many_lines(), workspace)

    assert workspace.interrupted is True
    assert result.interrupt_requested is True, (
        "a cancel without a reason must still request interrupt (#918)"
    )
    assert result.interrupt_reason is None
