"""A paired A/B of two cohorts on one roster (#2108, plan section 11).

The estimand is each case's pass^k from exactly its FIRST k judged trials (by
start time), which is binary, so discordant counts are well defined. Cases
short in either cohort are listed and left out of the pair.

Worst-case paired bounds compare the two adverse assignments over the whole
roster, A_lower - B_upper and A_upper - B_lower: same-direction recodings can
both show zero while the true difference spans [-1, 1], so they are not bounds.

Every interval is a paired bootstrap over cases with a fixed seed, computed
here so every reader gets the same interval.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from math import comb
from statistics import fmean
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.read_models.eval_sets import in_cohort
from syn_domain.contexts.orchestration.domain.read_models.eval_trial_metrics import require_k
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import TrialOutcome

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.orchestration.domain.read_models.eval_sets import Roster
    from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
        ClassifiedTrial,
        CohortKey,
    )

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 2108


@dataclass(frozen=True)
class Interval:
    """A 95% paired bootstrap percentile interval on a difference in means."""

    estimate: float
    low: float
    high: float


@dataclass(frozen=True)
class PairedComparison:
    a: CohortKey
    b: CohortKey
    k: int
    paired_cases: tuple[str, ...]
    short_cases: tuple[str, ...]
    """Fewer than k judged trials in either cohort: out of the pair."""
    coverage_complete: bool
    """Every rostered case has k judged trials in both cohorts; otherwise the call is inconclusive."""
    a_only: int
    """Paired cases where A passed all k and B did not."""
    b_only: int
    both: int
    neither: int
    mcnemar_p: float
    """Exact two-sided McNemar p over the discordant cases; 1.0 when there are none."""
    difference: Interval | None
    """Mean pass^k A - B over the paired cases; None when no case is paired."""
    a_lower_minus_b_upper: Interval | None
    """Whole roster, the assignment most adverse to A; None for an empty roster."""
    a_upper_minus_b_lower: Interval | None


def _by_start(trials: Sequence[ClassifiedTrial]) -> list[ClassifiedTrial]:
    return sorted(trials, key=lambda t: (t.run.started_at or "", t.run.execution_id))


def first_k_all_pass(trials: Sequence[ClassifiedTrial], k: int) -> bool | None:
    """Whether the first k JUDGED trials all passed; None when fewer than k are judged."""
    require_k(k)
    judged = [
        t.result for t in _by_start(trials) if t.result in (TrialOutcome.PASS, TrialOutcome.FAIL)
    ]
    if len(judged) < k:
        return None
    return all(r is TrialOutcome.PASS for r in judged[:k])


def first_k_bounds(trials: Sequence[ClassifiedTrial], k: int) -> tuple[float, float]:
    """(lower, upper) of the first-k pass^k with infra errors a fail, then a pass.

    Over the first k RESOLVED trials (judged or infra error); a case with fewer
    is 0 and 1.
    """
    require_k(k)
    resolved = [
        t.result
        for t in _by_start(trials)
        if t.result in (TrialOutcome.PASS, TrialOutcome.FAIL, TrialOutcome.INFRA_ERROR)
    ][:k]
    if len(resolved) < k:
        return 0.0, 1.0
    lower = all(r is TrialOutcome.PASS for r in resolved)
    upper = all(r is not TrialOutcome.FAIL for r in resolved)
    return float(lower), float(upper)


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact McNemar: binomial(b + c, 1/2) at the smaller discordant count."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_bootstrap(
    diffs: Sequence[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED
) -> Interval | None:
    """95% percentile interval on the mean of per-case paired differences."""
    if not diffs:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(fmean(rng.choices(diffs, k=n)) for _ in range(resamples))
    low = means[int(0.025 * resamples)]
    high = means[min(resamples - 1, int(0.975 * resamples))]
    return Interval(fmean(diffs), low, high)


def _require_roster_version(roster: Roster, *cohorts: CohortKey) -> None:
    for side in cohorts:
        if side.suite_version != roster.version:
            msg = (
                f"cohort of suite version {side.suite_version} cannot be paired on "
                f"the version {roster.version} roster"
            )
            raise ValueError(msg)


def compare_cohorts(
    roster: Roster,
    trials: Mapping[str, Sequence[ClassifiedTrial]],
    a: CohortKey,
    b: CohortKey,
    k: int,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> PairedComparison:
    """Paired comparison of cohorts A and B; ``trials`` is ``classify_roster_trials`` output.

    Both cohorts must be of the roster's version: pairing a v1 cohort against
    a v2 roster would silently drop every case v1 does not have.
    """
    require_k(k)
    _require_roster_version(roster, a, b)
    paired: list[tuple[str, bool, bool]] = []
    short: list[str] = []
    adverse_to_a: list[float] = []
    adverse_to_b: list[float] = []
    for case in roster.cases:
        ta = in_cohort(trials.get(case.eval_id, ()), a)
        tb = in_cohort(trials.get(case.eval_id, ()), b)
        pa, pb = first_k_all_pass(ta, k), first_k_all_pass(tb, k)
        if pa is None or pb is None:
            short.append(case.eval_id)
        else:
            paired.append((case.eval_id, pa, pb))
        a_low, a_high = first_k_bounds(ta, k)
        b_low, b_high = first_k_bounds(tb, k)
        adverse_to_a.append(a_low - b_high)
        adverse_to_b.append(a_high - b_low)
    tally = Counter((pa, pb) for _, pa, pb in paired)
    a_only, b_only = tally[True, False], tally[False, True]
    return PairedComparison(
        a=a,
        b=b,
        k=k,
        paired_cases=tuple(e for e, _, _ in paired),
        short_cases=tuple(short),
        coverage_complete=not short,
        a_only=a_only,
        b_only=b_only,
        both=tally[True, True],
        neither=tally[False, False],
        mcnemar_p=mcnemar_exact_p(a_only, b_only),
        difference=paired_bootstrap(
            [float(pa) - float(pb) for _, pa, pb in paired], resamples, seed
        ),
        a_lower_minus_b_upper=paired_bootstrap(adverse_to_a, resamples, seed),
        a_upper_minus_b_lower=paired_bootstrap(adverse_to_b, resamples, seed),
    )
