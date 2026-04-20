"""Unit tests for syn_shared.display.formatters."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_shared.display import (
    format_cost,
    format_duration_seconds,
    format_model_compact,
    format_phase,
    format_tokens,
)

EM_DASH = "\u2014"


class TestFormatTokens:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, EM_DASH),
            (0, "0"),
            (1, "1"),
            (742, "742"),
            (999, "999"),
            (1_000, "1.0k"),
            (1_237, "1.2k"),
            (12_500, "12.5k"),
            (999_999, "1000.0k"),
            (1_000_000, "1.0M"),
            (1_500_000, "1.5M"),
        ],
    )
    def test_renders_expected_string(self, value: int | None, expected: str) -> None:
        assert format_tokens(value) == expected


class TestFormatCost:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, EM_DASH),
            (0, "$0.00"),
            (Decimal("0"), "$0.00"),
            (0.001, "<$0.01"),
            (Decimal("0.0049"), "<$0.01"),
            (Decimal("0.01"), "$0.01"),
            (0.0438, "$0.04"),
            (1.234, "$1.23"),
            (12.5, "$12.50"),
            (Decimal("999.99"), "$999.99"),
            (Decimal("1000"), "$1.0k"),
            (Decimal("1234.5"), "$1.2k"),
        ],
    )
    def test_renders_expected_string(self, value: float | Decimal | None, expected: str) -> None:
        assert format_cost(value) == expected

    def test_negative(self) -> None:
        assert format_cost(Decimal("-0.05")) == "-$0.05"


class TestFormatDurationSeconds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, EM_DASH),
            (0, "<1s"),
            (0.4, "<1s"),
            (1, "1s"),
            (5, "5s"),
            (59, "59s"),
            (60, "1m"),
            (61, "1m 1s"),
            (134.2, "2m 14s"),
            (3600, "1h"),
            (3725, "1h 2m"),
        ],
    )
    def test_renders_expected_string(self, value: float | None, expected: str) -> None:
        assert format_duration_seconds(value) == expected


class TestFormatModelCompact:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ("", ""),
            ("claude-sonnet-4-6", "Sonnet 4.6"),
            ("claude-opus-4-7", "Opus 4.7"),
            ("claude-haiku-4-5", "Haiku 4.5"),
            # Dated suffixes are not numeric-only after splitting; pass through
            ("claude-opus-4-20250514", "claude-opus-4-20250514"),
            ("gpt-4o", "gpt-4o"),
            ("custom-model", "custom-model"),
        ],
    )
    def test_renders_expected_string(self, value: str | None, expected: str | None) -> None:
        assert format_model_compact(value) == expected


class TestFormatPhase:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ("", ""),
            ("detect", "Detect"),
            ("research_phase", "Research Phase"),
            ("fix-bug", "Fix Bug"),
            ("multi_word_phase_name", "Multi Word Phase Name"),
            ("ALREADY_TITLED", "Already Titled"),
            (
                "39574120-df6e-4043-a2aa-58be12c9ae51",
                "Phase 39574120",
            ),
            (
                "00000000-0000-0000-0000-000000000000",
                "Phase 00000000",
            ),
        ],
    )
    def test_renders_expected_string(self, value: str | None, expected: str | None) -> None:
        assert format_phase(value) == expected
