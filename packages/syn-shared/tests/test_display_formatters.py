"""Unit tests for syn_shared.display.formatters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from syn_shared.display import (
    compute_duration_seconds,
    format_cost,
    format_duration_seconds,
    format_model_compact,
    format_phase,
    format_repos,
    format_tokens,
)

EM_DASH = "\u2014"


@pytest.mark.unit
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


@pytest.mark.unit
class TestFormatCost:
    """NOTE the ``unit`` marker above.

    It was missing, so CI's ``pytest -m unit`` never ran a single one of these
    cases - the same silent-hole failure documented in
    ``session_cost/test_cost_model_resolution.py``. Every class in this file
    needs it.
    """

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


@pytest.mark.unit
class TestFormatCostCoverage:
    """``$0.00`` must not be able to mean "we could not price this" (#890)."""

    def test_zero_with_unpriced_observations_is_not_a_dollar_figure(self) -> None:
        assert format_cost(Decimal("0"), 1) == "unpriced"

    def test_zero_with_no_unpriced_observations_is_still_free(self) -> None:
        """A known model that burned nothing really did cost $0."""
        assert format_cost(Decimal("0"), 0) == "$0.00"

    def test_partial_coverage_marks_the_total_as_a_lower_bound(self) -> None:
        assert format_cost(Decimal("12.50"), 3) == ">=$12.50 (partial)"

    def test_none_stays_an_em_dash_regardless_of_coverage(self) -> None:
        assert format_cost(None, 5) == EM_DASH

    def test_default_coverage_preserves_the_original_rendering(self) -> None:
        """The parameter is additive: existing callers must not shift output."""
        assert format_cost(Decimal("1.234")) == format_cost(Decimal("1.234"), 0)


@pytest.mark.unit
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


@pytest.mark.unit
class TestComputeDurationSeconds:
    """The single read-time definition shared by the execution and session
    routes -- both must agree on what "how long has this been running" means
    for something that has not completed yet.
    """

    def test_none_started_at_is_unknown_not_zero(self) -> None:
        # A missing started_at is genuinely unknown; 0.0 would be a lie --
        # indistinguishable from "just started this instant".
        assert compute_duration_seconds(None) is None

    def test_unparseable_string_is_unknown_not_zero(self) -> None:
        assert compute_duration_seconds("not-a-timestamp") is None

    def test_empty_string_is_unknown(self) -> None:
        assert compute_duration_seconds("") is None

    def test_computes_elapsed_from_iso_string(self) -> None:
        now = datetime(2026, 9, 1, 12, 0, 30, tzinfo=UTC)
        started = "2026-09-01T12:00:00+00:00"
        assert compute_duration_seconds(started, now=now) == 30.0

    def test_computes_elapsed_from_trailing_z_suffix(self) -> None:
        # RFC 3339 'Z' suffix is what most of our stored timestamps use;
        # datetime.fromisoformat() rejects it directly on Python < 3.11.
        now = datetime(2026, 9, 1, 12, 1, 0, tzinfo=UTC)
        started = "2026-09-01T12:00:00Z"
        assert compute_duration_seconds(started, now=now) == 60.0

    def test_computes_elapsed_from_datetime_object(self) -> None:
        now = datetime(2026, 9, 1, 12, 0, 45, tzinfo=UTC)
        started = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
        assert compute_duration_seconds(started, now=now) == 45.0

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        now = datetime(2026, 9, 1, 12, 0, 10)  # naive
        started = datetime(2026, 9, 1, 12, 0, 0)  # naive
        assert compute_duration_seconds(started, now=now) == 10.0

    def test_advances_between_two_calls_without_a_fixed_now(self) -> None:
        # No `now` override: this is what the route layer actually calls.
        # A frozen or memoized value here is exactly the bug that got six
        # healthy workflow runs cancelled on 2026-09-01.
        started = datetime.now(UTC) - timedelta(seconds=5)
        first = compute_duration_seconds(started)
        second = compute_duration_seconds(started)
        assert first is not None
        assert second is not None
        assert second >= first


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestFormatRepos:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ([], None),
            ((), None),
            (["acme/foo"], "foo"),
            (["acme/foo", "acme/bar"], "foo +1"),
            (["acme/foo", "acme/bar", "acme/baz"], "foo +2"),
            (["  acme/foo  ", "", "acme/bar"], "foo +1"),
            (["singletoken"], "singletoken"),
        ],
    )
    def test_renders_expected_string(
        self, value: list[str] | tuple[str, ...] | None, expected: str | None
    ) -> None:
        assert format_repos(value) == expected
