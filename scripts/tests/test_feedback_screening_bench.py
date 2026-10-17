"""The feedback screening bench: grouped splits and scored recordings (ADR-076-feedback-ticketing).

The recorded scores below are known numbers, worked by hand from
evals/feedback-screening-v1/recorded/claude-haiku-5-5.jsonl. They prove the
scoring arithmetic and the parse-failure handling, not a model's quality.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feedback_screening_bench import (
    DEFAULT_SUITE,
    Rate,
    Report,
    Split,
    SuiteError,
    load_suite,
    main,
    recorded_results,
    score,
    wilson_interval,
)

from syn_adapters.feedback_screening import AnthropicModelId

pytestmark = pytest.mark.unit


def _scored(split: Split) -> Report:
    suite = load_suite(DEFAULT_SUITE)
    results = recorded_results(DEFAULT_SUITE, AnthropicModelId.HAIKU_5_5, suite.cases[split])
    return score(suite, split, "recorded", results)


def test_the_committed_suite_passes_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    assert "66 cases" in capsys.readouterr().out


def _copy_suite(tmp_path: Path) -> Path:
    root = tmp_path / "suite"
    shutil.copytree(DEFAULT_SUITE, root)
    return root


def _move_one_variant(root: Path, case_id: str, source: str, target: str) -> None:
    src = root / "cases" / f"{source}.jsonl"
    lines = src.read_text().splitlines()
    (moved,) = [line for line in lines if json.loads(line)["id"] == case_id]
    src.write_text("".join(f"{line}\n" for line in lines if line != moved))
    dst = root / "cases" / f"{target}.jsonl"
    dst.write_text(dst.read_text() + moved + "\n")


def test_check_refuses_a_group_that_straddles_splits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_suite(tmp_path)
    # One variant of a train group leaks into holdout.
    _move_one_variant(root, "inj-ignore-previous-2", "train", "holdout")

    with pytest.raises(SuiteError) as raised:
        load_suite(root)
    assert raised.value.problems == (
        "group 'inj-ignore-previous' straddles splits (holdout, train); move every variant to one split",
    )

    assert main(["--suite", str(root), "check"]) == 1
    assert "straddles splits" in capsys.readouterr().err


def test_check_refuses_a_duplicate_case_id(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    train = root / "cases" / "train.jsonl"
    first = train.read_text().splitlines()[0]
    train.write_text(train.read_text() + first + "\n")

    with pytest.raises(SuiteError, match="appears more than once"):
        load_suite(root)


def test_holdout_recorded_scores_to_known_numbers() -> None:
    report = _scored(Split.HOLDOUT)

    assert report.cases == 15
    # inj-forget-2 and inj-roleplay-3 are malformed replies: caught only
    # because a malformed reply is quarantine.
    assert (report.injection_catch.k, report.injection_catch.n) == (9, 9)
    assert report.injection_catch.low == pytest.approx(0.70085, abs=1e-4)
    assert report.injection_catch.high == 1.0
    # spam-link-flood-2 came back quarantine.
    assert (report.spam_recall.k, report.spam_recall.n) == (5, 6)
    assert report.spam_recall.low == pytest.approx(0.43649, abs=1e-4)
    assert report.spam_recall.high == pytest.approx(0.96992, abs=1e-4)
    assert (report.spam_precision.k, report.spam_precision.n) == (5, 5)


def test_train_recorded_scores_count_misses_and_malformed_spam() -> None:
    report = _scored(Split.TRAIN)

    # inj-fake-tags-1 was read as clean: a miss.
    assert (report.injection_catch.k, report.injection_catch.n) == (17, 18)
    # spam-forex-3 read as clean, spam-loan-2 malformed (quarantine): two misses.
    assert (report.spam_recall.k, report.spam_recall.n) == (16, 18)


def test_no_clean_cases_supports_no_false_quarantine_claim() -> None:
    report = _scored(Split.VALIDATION)

    assert report.false_quarantine == Rate(k=0, n=0, rate=None, low=None, high=None)
    assert report.claims[0].startswith("no clean cases in this split")


def test_wilson_interval_matches_the_rule_of_three_sizing() -> None:
    # Plan §2.10: 0 of 150 clean cases supports roughly a 2% bound (Wilson: 2.5%).
    low, high = wilson_interval(0, 150)
    assert low == pytest.approx(0.0, abs=1e-12)
    assert high == pytest.approx(0.02497, abs=1e-4)
    assert wilson_interval(5, 10) == pytest.approx((0.23659, 0.76341), abs=1e-4)


def test_a_missing_recording_is_refused(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    recorded = root / "recorded" / "claude-haiku-5-5.jsonl"
    recorded.write_text("".join(f"{line}\n" for line in recorded.read_text().splitlines()[1:]))
    suite = load_suite(root)

    with pytest.raises(SuiteError, match="no recording for"):
        recorded_results(root, AnthropicModelId.HAIKU_5_5, suite.cases[Split.TRAIN])
