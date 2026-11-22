"""An eval set's roster and per-cohort summary (#2108): T2, T6, T7, T10, and the roster read."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_sets import (
    Coverage,
    Roster,
    TaggedEval,
    roster_of,
    summarize_eval_set,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trial_metrics import Bounds

from .eval_trial_builders import cohort, cohort_tags, run

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunFacts

pytestmark = pytest.mark.unit

PASS, FAIL = Verdict.PASS, Verdict.FAIL


def _roster(n: int, *, version: str = "1") -> Roster:
    evals = [
        TaggedEval(
            f"eval-{i:02d}", ("suite:verifier-seed-v1", f"suite-version:{version}", "split:train")
        )
        for i in range(n)
    ]
    return roster_of(evals, "verifier-seed-v1", version)


def _runs(
    eval_id: str, *verdicts: Verdict, tags: tuple[str, ...] | None = None
) -> list[EvalRunFacts]:
    return [run(v, eval_id=eval_id, tags=tags) for v in verdicts]


def test_t2_the_2108_example_gives_90_70_20() -> None:
    # 10 cases at k = 3: 7 always pass, 2 sometimes, 1 never.
    roster = _roster(10)
    ids = [c.eval_id for c in roster.cases]
    runs = {e: _runs(e, PASS, PASS, PASS) for e in ids[:7]}
    runs |= {e: _runs(e, PASS, FAIL, PASS) for e in ids[7:9]}
    runs[ids[9]] = _runs(ids[9], FAIL, FAIL, FAIL)

    (summary,) = summarize_eval_set(roster, runs, 3).cohorts

    assert summary.cohort == cohort()
    assert summary.mean_pass_at_k == pytest.approx(0.9)
    assert summary.mean_pass_hat_k == pytest.approx(0.7)
    assert summary.flakiness == pytest.approx(0.2)
    assert summary.flaky_cases == tuple(ids[7:9])
    assert summary.coverage == Coverage(roster_size=10, complete=10, short=0, never_launched=0)
    assert not summary.partial
    # Complete, no infra errors: the bounds collapse onto the figure.
    bounds = summary.pass_hat_k_bounds
    assert (bounds.lower, bounds.upper) == (pytest.approx(0.7), pytest.approx(0.7))


def test_t6_two_scoring_protocols_never_pool() -> None:
    roster = _roster(1)
    (e,) = [c.eval_id for c in roster.cases]
    keyword = _runs(e, PASS, PASS, PASS)
    judged = [
        run(FAIL, eval_id=e, tags=cohort_tags(scorer="llm-panel-v1"), scorer_version="llm-panel-v1")
        for _ in range(3)
    ]

    summary = summarize_eval_set(roster, {e: keyword + judged}, 3)

    by_protocol = {c.cohort.scorer_protocol: c for c in summary.cohorts}
    assert set(by_protocol) == {"keyword-v1", "llm-panel-v1"}
    assert by_protocol["keyword-v1"].mean_pass_hat_k == 1.0
    assert by_protocol["llm-panel-v1"].mean_pass_hat_k == 0.0
    assert all(c.cases[0].counts.judged == 3 for c in summary.cohorts)


def test_another_suite_version_is_another_cohort_and_not_on_this_roster() -> None:
    roster = _roster(1)
    (e,) = [c.eval_id for c in roster.cases]
    summary = summarize_eval_set(
        roster, {e: _runs(e, PASS, PASS, PASS, tags=cohort_tags(version="2"))}, 3
    )
    assert summary.cohorts == ()


def test_t7_a_rostered_case_with_no_trials_is_never_launched_and_marks_the_mean_partial() -> None:
    roster = _roster(3)
    ids = [c.eval_id for c in roster.cases]
    runs = {ids[0]: _runs(ids[0], PASS, PASS, PASS), ids[1]: _runs(ids[1], PASS)}

    (summary,) = summarize_eval_set(roster, runs, 3).cohorts

    assert summary.coverage == Coverage(roster_size=3, complete=1, short=1, never_launched=1)
    assert summary.partial
    assert summary.cases[2].never_launched
    assert summary.cases[2].trials_short == 3
    # The conditional mean is over the one complete case: descriptive only.
    assert summary.mean_pass_hat_k == 1.0


def test_t7_a_never_launched_case_alone_still_marks_the_mean_partial() -> None:
    roster = _roster(2)
    ids = [c.eval_id for c in roster.cases]

    (summary,) = summarize_eval_set(roster, {ids[0]: _runs(ids[0], PASS, PASS, PASS)}, 3).cohorts

    assert summary.coverage == Coverage(roster_size=2, complete=1, short=0, never_launched=1)
    assert summary.partial


def test_t10_a_short_case_widens_the_roster_wide_bounds() -> None:
    roster = _roster(2)
    ids = [c.eval_id for c in roster.cases]
    complete = {e: _runs(e, PASS, PASS, PASS) for e in ids}
    one_short = {ids[0]: complete[ids[0]], ids[1]: _runs(ids[1], PASS, PASS)}

    (full,) = summarize_eval_set(roster, complete, 3).cohorts
    (short,) = summarize_eval_set(roster, one_short, 3).cohorts

    assert full.pass_hat_k_bounds == Bounds(1.0, 1.0)
    # The short case is 0 in the lower bound, so dropping it cannot flatter the set.
    assert short.pass_hat_k_bounds == Bounds(0.5, 1.0)
    assert short.mean_pass_hat_k == 1.0
    assert short.partial


def test_infra_share_and_exclusions_are_counted_per_cohort() -> None:
    roster = _roster(1)
    (e,) = [c.eval_id for c in roster.cases]
    infra = run(
        None,
        eval_id=e,
        status=ExecutionStatus.FAILED,
        classification=FailureClassification.PLATFORM,
    )
    attached = run(PASS, eval_id=e, kind=AssociationKind.ATTACHED)
    summary = summarize_eval_set(roster, {e: [*_runs(e, PASS, PASS, PASS), infra, attached]}, 3)

    (cohort_summary,) = summary.cohorts
    assert cohort_summary.infra_error_count == 1
    assert cohort_summary.infra_share == pytest.approx(0.25)
    assert summary.not_a_trial_count == 1


def test_the_roster_is_read_from_suite_and_version_tags_and_filtered_by_split() -> None:
    evals = [
        TaggedEval(
            "e-a",
            ("suite:s", "suite-version:1", "suite-version:2", "split:train", "polarity:defect"),
        ),
        TaggedEval("e-b", ("suite:s", "suite-version:2", "split:holdout", "polarity:clean")),
        TaggedEval("e-c", ("suite:other", "suite-version:2", "split:holdout")),
        TaggedEval("e-d", ("suite:s", "suite-version:3", "split:train")),
    ]

    v2 = roster_of(evals, "s", "2")
    assert [c.eval_id for c in v2.cases] == ["e-a", "e-b"]
    assert [(c.split, c.polarity) for c in v2.cases] == [("train", "defect"), ("holdout", "clean")]
    assert [c.eval_id for c in roster_of(evals, "s", "2", split="holdout").cases] == ["e-b"]
    assert [c.eval_id for c in roster_of(evals, "s", "1").cases] == ["e-a"]
