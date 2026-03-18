"""Tests for output formatting helpers."""

from __future__ import annotations

import pytest

from syn_cli._output import format_breakdown, format_duration, format_timestamp


@pytest.mark.unit
class TestFormatDuration:
    def test_milliseconds(self) -> None:
        assert format_duration(500) == "500ms"

    def test_seconds(self) -> None:
        assert format_duration(1200) == "1.2s"

    def test_minutes_and_seconds(self) -> None:
        assert format_duration(135_000) == "2m 15s"

    def test_minutes_even(self) -> None:
        assert format_duration(120_000) == "2m"

    def test_hours_and_minutes(self) -> None:
        assert format_duration(5_400_000) == "1h 30m"

    def test_hours_even(self) -> None:
        assert format_duration(3_600_000) == "1h"


@pytest.mark.unit
class TestFormatTimestamp:
    def test_none_returns_dash(self) -> None:
        assert format_timestamp(None) == "-"

    def test_valid_iso(self) -> None:
        result = format_timestamp("2026-03-16T14:30:00+00:00")
        assert "Mar" in result or "16" in result

    def test_invalid_returns_original(self) -> None:
        assert format_timestamp("not-a-date") == "not-a-date"

    def test_naive_datetime(self) -> None:
        result = format_timestamp("2026-03-16T14:30:00")
        assert "Mar" in result or "16" in result


@pytest.mark.unit
class TestFormatBreakdown:
    def test_creates_table(self) -> None:
        table = format_breakdown({"claude-sonnet": "$1.23", "claude-opus": "$4.56"}, "By Model")
        assert table.title == "By Model"
        assert len(table.rows) == 2
