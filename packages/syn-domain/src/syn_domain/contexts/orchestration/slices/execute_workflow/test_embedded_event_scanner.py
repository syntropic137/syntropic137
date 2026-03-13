"""Tests for EmbeddedEventScanner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.EmbeddedEventScanner import (
    EmbeddedEventScanner,
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
        content = json.dumps(
            {"event_type": "tool_execution_started", "session_id": "s-1", "timestamp": "t1"}
        )
        await scanner.scan_and_record(content, "Bash")
        assert len(collector.embedded_events) == 1
        assert collector.embedded_events[0][0] == "tool_execution_started"

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
        valid = json.dumps(
            {"event_type": "tool_execution_completed", "session_id": "s-1", "timestamp": "t1"}
        )
        content = f"regular output\n{valid}\nmore text\n"
        await scanner.scan_and_record(content, "Bash")
        assert len(collector.embedded_events) == 1
