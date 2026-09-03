"""Unit tests for syn_shared.display.formatters."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from syn_shared.display import (
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
class TestResolveDurationSeconds:
    """The one definition of "how long did this run" shared by every read
    surface -- execution list and detail, phases, sessions, repo and system
    activity. They must agree about the same run at the same instant.
    """

    # -- Not started ---------------------------------------------------------

    @pytest.mark.parametrize("status", ["pending", "PENDING", " Pending ", "not_started"])
    def test_pending_is_unknown_not_zero(self, status: str) -> None:
        # A pending phase carries the execution's started_at in some stores, so
        # a span IS computable -- it just is not this phase's duration. It has
        # not run. Reporting 0.0 renders as "completed instantly" (#1076 review
        # finding 3), and the case-varied spellings are here because the
        # previous implementation matched `== "running"` exactly and so treated
        # "PENDING" as finished.
        started = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
        ended = datetime(2026, 9, 1, 12, 5, 0, tzinfo=UTC)
        assert resolve_duration_seconds(status, started_at=started, ended_at=ended) is None

    # -- In flight -----------------------------------------------------------

    def test_running_measures_against_now_not_the_recorded_value(self) -> None:
        # THE regression this function exists to prevent. A running phase has a
        # stale recorded duration in the projection; reading it back reports a
        # frozen number that looks like a hang. 100s of real elapsed time
        # cannot be produced by returning the 7.5 that is stored.
        started = datetime.now(UTC) - timedelta(seconds=100)
        resolved = resolve_duration_seconds("running", started_at=started, recorded_seconds=7.5)
        assert resolved is not None
        assert resolved == pytest.approx(100.0, abs=5.0)

    @pytest.mark.parametrize("status", ["running", "RUNNING", "Running", "paused"])
    def test_in_flight_statuses_advance_between_two_reads(self, status: str) -> None:
        # A frozen, cached or memoized value is exactly what got six healthy
        # workflow runs cancelled on 2026-09-01: the duration stopped moving
        # and was read as a hang.
        #
        # STRICTLY greater, and by at least the time actually slept. `>=` (the
        # assertion this replaces) passes against `return 42.0`, against a
        # memoized first result, and against any constant -- it cannot fail
        # against the regression it was written to catch.
        started = datetime.now(UTC) - timedelta(seconds=5)
        first = resolve_duration_seconds(status, started_at=started)
        slept = 0.05
        time.sleep(slept)
        second = resolve_duration_seconds(status, started_at=started)

        assert first is not None
        assert second is not None
        assert second > first, (
            f"{status!r} duration did not advance across a {slept}s sleep "
            f"({first} -> {second}); it is frozen, cached or a constant"
        )
        assert second - first >= slept * 0.5

    def test_running_accepts_an_explicit_now_for_deterministic_callers(self) -> None:
        # The projection closes out a cancelled phase at the instant it ended,
        # not at read time.
        assert (
            resolve_duration_seconds(
                "running",
                started_at="2026-09-01T12:00:00Z",
                now="2026-09-01T12:00:30Z",
            )
            == 30.0
        )

    # -- Finished ------------------------------------------------------------

    def test_finished_prefers_the_duration_measured_at_the_source(self) -> None:
        assert (
            resolve_duration_seconds(
                "completed",
                started_at="2026-09-01T12:00:00Z",
                ended_at="2026-09-01T12:05:00Z",
                recorded_seconds=42.5,
            )
            == 42.5
        )

    def test_finished_without_a_recorded_value_uses_the_timestamp_span(self) -> None:
        assert (
            resolve_duration_seconds(
                "completed",
                started_at="2026-09-01T12:00:00Z",
                ended_at="2026-09-01T12:05:00Z",
            )
            == 300.0
        )

    def test_finished_recorded_zero_is_kept_as_a_real_measurement(self) -> None:
        # The one place 0.0 is legitimate: something measured it and got zero.
        assert (
            resolve_duration_seconds(
                "completed",
                started_at="2026-09-01T12:00:00Z",
                ended_at="2026-09-01T12:05:00Z",
                recorded_seconds=0.0,
            )
            == 0.0
        )

    def test_unrecognised_status_is_treated_as_finished(self) -> None:
        # A status added elsewhere can only ever under-report (None), never
        # invent a live duration that grows forever.
        assert resolve_duration_seconds("quiesced", started_at=datetime.now(UTC)) is None

    def test_naive_datetimes_are_treated_as_utc(self) -> None:
        assert (
            resolve_duration_seconds(
                "completed",
                started_at=datetime(2026, 9, 1, 12, 0, 0),
                ended_at=datetime(2026, 9, 1, 12, 0, 10),
            )
            == 10.0
        )

    # -- Unmeasurable --------------------------------------------------------

    @pytest.mark.parametrize("started", [None, "", "   ", "not-a-timestamp", 12345])
    def test_unusable_started_at_is_unknown_not_zero(self, started: object) -> None:
        assert (
            resolve_duration_seconds(
                "running",
                started_at=started,  # pyright: ignore[reportArgumentType] - hostile input
            )
            is None
        )

    def test_malformed_timestamp_is_logged_as_corruption(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # An unparseable stored timestamp is corruption, not an absent value.
        # Silently returning 0.0 made the two indistinguishable downstream
        # (#1076 review finding 4).
        with caplog.at_level("WARNING"):
            assert (
                resolve_duration_seconds(
                    "completed", started_at="2026-13-45T99:99:99Z", ended_at="2026-09-01T12:00:00Z"
                )
                is None
            )
        assert any("Unparseable timestamp" in r.getMessage() for r in caplog.records)

    def test_future_started_at_is_unknown_not_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        # Clock skew, or a started_at in the future. The old code clamped the
        # negative span with max(..., 0.0), turning a broken clock into a
        # confident measurement of "no time at all".
        started = datetime.now(UTC) + timedelta(hours=1)
        with caplog.at_level("WARNING"):
            assert resolve_duration_seconds("running", started_at=started) is None
        assert any("negative" in r.getMessage() for r in caplog.records)

    def test_finished_without_an_end_timestamp_is_unknown(self) -> None:
        assert resolve_duration_seconds("completed", started_at="2026-09-01T12:00:00Z") is None

    def test_zero_is_never_returned_for_an_unknown(self) -> None:
        # The whole premise: None is the only unknown. Every unmeasurable
        # input above must not come back as a float at all.
        unknowns = [
            resolve_duration_seconds("pending", started_at="2026-09-01T12:00:00Z"),
            resolve_duration_seconds("completed", started_at=None, ended_at=None),
            resolve_duration_seconds("completed", started_at="garbage", ended_at="garbage"),
            resolve_duration_seconds("running", started_at=datetime.now(UTC) + timedelta(days=1)),
        ]
        assert unknowns == [None, None, None, None]


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
