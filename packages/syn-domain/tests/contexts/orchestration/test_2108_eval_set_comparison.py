"""The paired A/B of two cohorts on one roster (#2108, plan section 11): T9."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_set_comparison import (
    Interval,
    PairedComparison,
    compare_cohorts,
    first_k_all_pass,
    first_k_bounds,
    mcnemar_exact_p,
    paired_bootstrap,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_sets import (
    TaggedEval,
    classify_roster_trials,
    roster_of,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
    ClassifiedTrial,
    classify_trial,
)

from .eval_trial_builders import cohort, cohort_tags, run

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunFacts

pytestmark = pytest.mark.unit

P, F = Verdict.PASS, Verdict.FAIL
B_MODELS = "n" * 64
A, B = cohort(), cohort(models=B_MODELS)


def _arm(eval_id: str, verdicts: str, *, models: str | None = None) -> list[EvalRunFacts]:
    tags = cohort_tags(models=models) if models else None
    return [_trial_run(v, eval_id, tags) for v in verdicts]


def _trial_run(v: str, eval_id: str, tags: tuple[str, ...] | None) -> EvalRunFacts:
    """``P`` pass, ``F`` fail, ``I`` a platform failure (infra error)."""
    if v == "I":
        return run(
            None,
            eval_id=eval_id,
            tags=tags,
            status=ExecutionStatus.FAILED,
            classification=FailureClassification.PLATFORM,
        )
    return run(P if v == "P" else F, eval_id=eval_id, tags=tags)


# case -> (A's trials, B's trials), in start order
FIXTURE = {
    "e0": ("PPP", "PPP"),  # both
    "e1": ("PPP", "PFP"),  # A only
    "e2": ("PPP", "FFF"),  # A only
    "e3": ("PPP", "FFP"),  # A only
    "e4": ("FFF", "FFF"),  # neither
    "e5": ("PP", "PPP"),  # A short: out of the pair
    "e6": ("PPP", "PPI"),  # B short by an infra error: out of the pair, [0, 1] for B
}


def _infra_trial() -> ClassifiedTrial:
    return classify_trial(
        run(None, status=ExecutionStatus.FAILED, classification=FailureClassification.PLATFORM)
    )


def _compare() -> PairedComparison:
    evals = [TaggedEval(e, ("suite:s", "suite-version:1")) for e in FIXTURE]
    roster = roster_of(evals, "s", "1")
    runs = {e: _arm(e, a) + _arm(e, b, models=B_MODELS) for e, (a, b) in FIXTURE.items()}
    return compare_cohorts(roster, classify_roster_trials(roster, runs), A, B, 3)


def test_t9_fixed_fixture_gives_fixed_counts_p_and_intervals() -> None:
    result = _compare()

    assert result.paired_cases == ("e0", "e1", "e2", "e3", "e4")
    assert result.short_cases == ("e5", "e6")
    assert not result.coverage_complete
    assert (result.a_only, result.b_only, result.both, result.neither) == (3, 0, 1, 1)
    # 2 * P(X <= 0), X ~ Binomial(3, 1/2) = 2 * 1/8
    assert result.mcnemar_p == pytest.approx(0.25)

    assert result.difference is not None
    assert result.difference.estimate == pytest.approx(0.6)
    assert (result.difference.low, result.difference.high) == (pytest.approx(0.2), 1.0)

    # Adverse to A: e5 is A's 0 against B's 1, e6 A's 1 against B's 1 -> (0+1+1+1+0-1+0)/7.
    assert result.a_lower_minus_b_upper is not None
    assert result.a_lower_minus_b_upper.estimate == pytest.approx(2 / 7)
    # Adverse to B: e5 is A's 1 against B's 1, e6 A's 1 against B's 0 -> (0+1+1+1+0+0+1)/7.
    assert result.a_upper_minus_b_lower is not None
    assert result.a_upper_minus_b_lower.estimate == pytest.approx(4 / 7)
    for interval in (result.difference, result.a_lower_minus_b_upper, result.a_upper_minus_b_lower):
        assert interval.low <= interval.estimate <= interval.high


def test_t9_the_interval_is_the_same_on_every_read() -> None:
    assert _compare() == _compare()


def test_the_paired_estimand_is_the_first_k_judged_trials_by_start() -> None:
    trials = [classify_trial(run(P)), _infra_trial(), *(classify_trial(run(v)) for v in (P, P, F))]
    # The infra error is skipped; the late FAIL is the fourth judged trial.
    assert first_k_all_pass(trials, 3) is True
    assert first_k_all_pass(trials[:3], 3) is None
    # In the bounds the infra error is one of the first three resolved trials.
    assert first_k_bounds(trials, 3) == (0.0, 1.0)
    assert first_k_bounds(trials[:2], 3) == (0.0, 1.0)
    assert first_k_bounds([classify_trial(run(P)) for _ in range(3)], 3) == (1.0, 1.0)
    assert first_k_bounds([classify_trial(run(F)), _infra_trial(), classify_trial(run(P))], 3) == (
        0.0,
        0.0,
    )


@pytest.mark.parametrize(
    ("b", "c", "p"), [(0, 0, 1.0), (3, 0, 0.25), (0, 3, 0.25), (5, 1, 2 * 7 / 64), (2, 2, 1.0)]
)
def test_mcnemar_exact_two_sided(b: int, c: int, p: float) -> None:
    assert mcnemar_exact_p(b, c) == pytest.approx(p)


def test_no_paired_case_has_no_interval() -> None:
    assert paired_bootstrap([]) is None
    assert paired_bootstrap([0.0, 0.0]) == Interval(0.0, 0.0, 0.0)
