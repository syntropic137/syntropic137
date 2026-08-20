"""Tests for derive_expected against the golden codex recording fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.validate_codex_observability import ExpectedEvents, derive_expected

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "packages/syn-domain/tests/fixtures/codex/codex_exec_recording.jsonl"
)


# Marked at module scope: this file sat outside pytest testpaths, so no CI
# job collected it and nothing here needed a marker. Collected now, an
# unmarked test is one no job runs - which the census gate refuses.
pytestmark = pytest.mark.unit


def _fixture_lines() -> list[str]:
    return _FIXTURE.read_text(encoding="utf-8").splitlines()


def test_derive_expected_matches_golden_recording() -> None:
    expected = derive_expected(_fixture_lines())
    # 2 command_execution (Bash) + 2 file_change (synthetic Edit pair) => 4 / 4.
    # 1 turn.completed => 1 token_usage; usage input=97006 cached=87808 out=288 reasoning=0.
    assert expected == ExpectedEvents(
        token_usage_events=1,
        tool_started=4,
        tool_completed=4,
        session_summary=1,
        fresh_input_tokens=9198,  # 97006 - 87808
        cache_read_tokens=87808,
        output_tokens=288,  # 288 + 0 reasoning
        turns=1,
        noise_lines=3,
    )


def test_derive_expected_tolerates_only_noise() -> None:
    expected = derive_expected(["not json", "", "ERROR codex_models_manager foo", "  "])
    assert expected.token_usage_events == 0
    assert expected.tool_started == 0
    assert expected.tool_completed == 0
    assert expected.session_summary == 1  # always emitted at end of stream
    assert expected.noise_lines == 2  # 2 junk lines; blank/whitespace lines are skipped


def test_derive_expected_ignores_agent_message_and_turn_started() -> None:
    lines = [
        '{"type": "thread.started", "thread_id": "t1"}',
        '{"type": "turn.started"}',
        '{"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}',
    ]
    expected = derive_expected(lines)
    assert expected.tool_started == 0
    assert expected.tool_completed == 0
    assert expected.token_usage_events == 0
