"""Unit tests for syn_shared.display.formatters."""

from __future__ import annotations

import logging
import time
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
    resolve_duration_seconds,
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

    def test_tracks_the_start_it_was_given_rather_than_returning_a_constant(self) -> None:
        # No `now` override: this is what the route layer actually calls.
        #
        # The regression to catch is a frozen or memoized value -- the bug that
        # got six healthy workflow runs cancelled on 2026-09-01. This test used
        # to assert `second >= first` for one start, which `return 42.0`
        # satisfies, so it could not fail against the very thing it named. Two
        # starts a known distance apart must come back a known distance apart:
        # any implementation ignoring its argument returns the same number for
        # both and the difference collapses to zero.
        now = datetime.now(UTC)
        recent = compute_duration_seconds(now - timedelta(seconds=5))
        older = compute_duration_seconds(now - timedelta(seconds=305))
        assert recent is not None
        assert older is not None
        assert recent == pytest.approx(5.0, abs=1.0)
        assert older - recent == pytest.approx(300.0, abs=1.0)

    def test_advances_between_two_calls_on_the_same_start(self) -> None:
        # Complements the test above, which a per-argument cache would pass:
        # the SAME start must give a strictly larger answer as time passes.
        started = datetime.now(UTC) - timedelta(seconds=5)
        first = compute_duration_seconds(started)
        time.sleep(0.05)
        second = compute_duration_seconds(started)
        assert first is not None
        assert second is not None
        assert second > first

    def test_start_after_the_reference_instant_is_unknown_not_zero(self) -> None:
        # Clock skew, or a bad write. Clamping to 0.0 (which this did) reports
        # "just started" for something that may have been running for an hour --
        # a confident measurement manufactured out of a defect.
        now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
        started = datetime(2026, 9, 1, 13, 0, 0, tzinfo=UTC)
        assert compute_duration_seconds(started, now=now) is None

    def test_malformed_timestamp_is_logged_not_silently_dropped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The VALUE is unknown either way, but a malformed timestamp is a data
        # defect whose only other symptom is a duration quietly going missing.
        with caplog.at_level(logging.WARNING):
            assert compute_duration_seconds("not-a-timestamp") is None
        assert any("not-a-timestamp" in r.getMessage() for r in caplog.records)

    def test_missing_timestamp_is_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        # Nothing started yet is an ordinary state, not a defect; logging it
        # would bury the malformed case above in noise.
        with caplog.at_level(logging.WARNING):
            assert compute_duration_seconds(None) is None
        assert caplog.records == []


@pytest.mark.unit
class TestResolveDurationSeconds:
    """The one rule every read surface applies, so none of them can disagree.

    Each case below arrives at some surface as a user-visible number; the
    property under test is that an UNKNOWN duration is never one of them.
    """

    def test_running_is_computed_live_from_started_at(self) -> None:
        now = datetime(2026, 9, 1, 12, 5, 0, tzinfo=UTC)
        assert (
            resolve_duration_seconds(
                "running",
                started_at="2026-09-01T12:00:00Z",
                recorded_seconds=0.0,
                now=now,
            )
            == 300.0
        )

    def test_paused_still_accrues_wall_clock_time(self) -> None:
        now = datetime(2026, 9, 1, 12, 5, 0, tzinfo=UTC)
        assert (
            resolve_duration_seconds("paused", started_at="2026-09-01T12:00:00Z", now=now) == 300.0
        )

    def test_pending_is_unknown_not_zero(self) -> None:
        # A pending phase has never started. 0.0 reads as "finished instantly",
        # which is how every not-yet-run phase reported a duration it never had.
        assert resolve_duration_seconds("pending", started_at=None, recorded_seconds=None) is None

    def test_completed_prefers_the_duration_recorded_at_completion(self) -> None:
        # Recorded beats derived: it was measured by whoever saw the completion.
        assert (
            resolve_duration_seconds(
                "completed",
                started_at="2026-09-01T12:00:00Z",
                completed_at="2026-09-01T12:05:00Z",
                recorded_seconds=33.004841,
            )
            == 33.004841
        )

    def test_a_recorded_zero_is_a_measurement_and_survives(self) -> None:
        # The other half of the contract: sub-millisecond phases are real, so
        # 0.0 must pass through unchanged. That is exactly why "no measurement"
        # has to be None -- the two are not interchangeable.
        assert (
            resolve_duration_seconds(
                "completed",
                started_at="2026-09-01T12:00:00Z",
                completed_at="2026-09-01T12:00:00Z",
                recorded_seconds=0.0,
            )
            == 0.0
        )

    def test_completed_without_a_record_derives_from_the_timestamps(self) -> None:
        assert (
            resolve_duration_seconds(
                "completed",
                started_at="2026-09-01T12:00:00Z",
                completed_at="2026-09-01T12:00:45Z",
            )
            == 45.0
        )

    def test_terminal_without_a_record_or_an_end_is_unknown(self) -> None:
        # A failed phase nobody timed. Not zero, and NOT a live duration that
        # would keep growing forever for something already dead.
        assert resolve_duration_seconds("failed", started_at="2026-09-01T12:00:00Z") is None

    def test_malformed_started_at_is_unknown_for_a_running_phase(self) -> None:
        assert resolve_duration_seconds("running", started_at="garbage") is None

    def test_future_started_at_is_unknown_for_a_running_phase(self) -> None:
        now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
        assert (
            resolve_duration_seconds(
                "running", started_at="2026-09-01T13:00:00Z", recorded_seconds=0.0, now=now
            )
            is None
        )


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
