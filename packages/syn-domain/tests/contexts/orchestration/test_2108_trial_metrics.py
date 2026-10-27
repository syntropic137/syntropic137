"""pass@k, pass^k, flakiness and the infra-error bounds of one case (#2108): T3, T4, T5, T8."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trial_metrics import (
    Bounds,
    CaseMetrics,
    case_metrics,
    pass_at_k,
    pass_hat_k,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import classify_trial

from .eval_trial_builders import run

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunFacts

pytestmark = pytest.mark.unit

PASS, FAIL = Verdict.PASS, Verdict.FAIL


def _infra() -> EvalRunFacts:
    return run(None, status=ExecutionStatus.FAILED, classification=FailureClassification.PLATFORM)


def _pending() -> EvalRunFacts:
    return run(None, status=ExecutionStatus.RUNNING)


def _case(*runs: EvalRunFacts, k: int = 3) -> CaseMetrics:
    return case_metrics("eval-1", [classify_trial(r) for r in runs], k)


@pytest.mark.parametrize(
    ("c", "at", "hat"),
    # n = 4, k = 3: C(4, 3) = 4, so pass@3 = 1 - C(4-c, 3)/4 and pass^3 = C(c, 3)/4.
    [(0, 0.0, 0.0), (1, 0.75, 0.0), (2, 1.0, 0.0), (3, 1.0, 0.25), (4, 1.0, 1.0)],
)
def test_t5_n4_k3_matches_the_closed_form(c: int, at: float, hat: float) -> None:
    assert pass_at_k(4, c, 3) == pytest.approx(at)
    assert pass_hat_k(4, c, 3) == pytest.approx(hat)
    metrics = _case(*(run(PASS) for _ in range(c)), *(run(FAIL) for _ in range(4 - c)))
    assert (metrics.pass_at_k, metrics.pass_hat_k) == (pytest.approx(at), pytest.approx(hat))
    assert metrics.flaky is (at > 0 and hat < 1)


def test_at_n_equal_k_the_estimators_are_once_and_every_time() -> None:
    assert _case(run(PASS), run(FAIL), run(FAIL)).pass_at_k == 1.0
    assert _case(run(PASS), run(FAIL), run(FAIL)).pass_hat_k == 0.0
    assert _case(run(PASS), run(PASS), run(PASS)).pass_hat_k == 1.0
    assert _case(run(FAIL), run(FAIL), run(FAIL)).pass_at_k == 0.0


def test_t4_fewer_than_k_judged_reports_trials_short_and_no_metric() -> None:
    metrics = _case(run(PASS), run(FAIL))
    assert metrics.trials_short == 1
    assert (metrics.pass_at_k, metrics.pass_hat_k, metrics.flaky) == (None, None, None)
    assert not metrics.complete


def test_t3_an_infra_error_leaves_n_and_lowers_only_the_lower_bound() -> None:
    clean = _case(run(PASS), run(PASS), run(PASS))
    with_infra = _case(run(PASS), run(PASS), run(PASS), _infra())
    assert with_infra.counts.judged == 3
    assert with_infra.counts.infra_errors == 1
    # The conditional figures do not move: the infra error is not a fail.
    assert (with_infra.pass_at_k, with_infra.pass_hat_k) == (clean.pass_at_k, clean.pass_hat_k)
    # As a fail it lowers pass^3: C(3,3)/C(4,3) = 1/4. As a pass nothing moves.
    assert with_infra.pass_hat_k_bounds == Bounds(0.25, 1.0)
    assert clean.pass_hat_k_bounds == Bounds(1.0, 1.0)
    assert with_infra.pass_at_k_bounds == Bounds(1.0, 1.0)


def test_t3_an_infra_error_is_still_a_retry_owed() -> None:
    metrics = _case(run(PASS), run(PASS), _infra())
    assert metrics.trials_short == 1
    assert metrics.pass_hat_k is None
    # Resolved trials reach k, so the bounds are computed, not [0, 1].
    assert metrics.pass_hat_k_bounds == Bounds(0.0, 1.0)
    assert metrics.pass_at_k_bounds == Bounds(1.0, 1.0)


def test_t8_pending_trials_reduce_trials_short() -> None:
    assert _case(run(PASS)).trials_short == 2
    assert _case(run(PASS), _pending()).trials_short == 1
    assert _case(run(PASS), _pending(), _pending()).trials_short == 0
    # An unscored completed run is pending too: it is reserved, not owed.
    assert _case(run(PASS), run(None), _pending()).trials_short == 0


def test_a_case_whose_infra_errors_reach_k_is_exhausted_and_owes_nothing() -> None:
    metrics = _case(_infra(), _infra(), _infra())
    assert metrics.exhausted
    assert metrics.trials_short == 0
    assert not _case(_infra(), _infra()).exhausted


def test_a_never_launched_case_is_short_by_k_and_spans_the_whole_bound() -> None:
    metrics = _case()
    assert metrics.never_launched
    assert metrics.trials_short == 3
    assert metrics.pass_hat_k_bounds == Bounds(0.0, 1.0)
