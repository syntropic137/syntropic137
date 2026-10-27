"""pass@k, pass^k and flakiness for one case of one cohort, with infra errors bounded (#2108).

With ``n`` judged trials (pass + fail) and ``c`` passes:

- pass@k = 1 - C(n-c, k) / C(n, k): the chance at least one of k trials passes;
- pass^k = C(c, k) / C(n, k): the chance all k pass;
- flaky = pass@k > 0 and pass^k < 1.

At n = k they are "passed at least once" and "passed every time". For n > k
they are the unbiased estimators (Chen et al. 2021 for pass@k; the same
counting argument for pass^k). For n < k there is no metric: the case is
short.

Infra errors are not scored as 0. They leave n, and the case is reported
three ways (plan section 6.1): conditional over judged trials, a lower bound
with every infra error a fail, and an upper bound with every infra error a
pass. A case short of k even counting infra errors is 0 in the lower bound and
1 in the upper, so dropping incomplete cases cannot select the easy ones.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import comb
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
    TrialExclusion,
    TrialOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
        ClassifiedTrial,
    )


def pass_at_k(n: int, c: int, k: int) -> float | None:
    """1 - C(n-c, k) / C(n, k); None when n < k."""
    if k < 1 or n < k:
        return None
    return 1 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float | None:
    """C(c, k) / C(n, k); None when n < k."""
    if k < 1 or n < k:
        return None
    return comb(c, k) / comb(n, k)


@dataclass(frozen=True)
class Bounds:
    """A figure with every infra error a fail (lower) and every one a pass (upper)."""

    lower: float
    upper: float


@dataclass(frozen=True)
class TrialCounts:
    """One case's trials in one cohort, by outcome, and the runs excluded from it."""

    passes: int = 0
    fails: int = 0
    infra_errors: int = 0
    pending: int = 0
    base_mismatch: int = 0
    treatment_mismatch: int = 0

    @property
    def judged(self) -> int:
        """n: the trials a rate is a fraction of. Infra errors and pending are not."""
        return self.passes + self.fails

    @property
    def resolved(self) -> int:
        """Judged trials plus infra errors: what the bounds are computed over."""
        return self.judged + self.infra_errors

    @property
    def launched(self) -> int:
        """Every trial, whatever its outcome. Excluded runs are not trials."""
        return self.resolved + self.pending

    @classmethod
    def of(cls, trials: Iterable[ClassifiedTrial]) -> TrialCounts:
        """Count classified trials; ``NOT_A_TRIAL`` belongs to no cohort and is not counted here."""
        tally = Counter(t.result for t in trials)
        return cls(
            passes=tally[TrialOutcome.PASS],
            fails=tally[TrialOutcome.FAIL],
            infra_errors=tally[TrialOutcome.INFRA_ERROR],
            pending=tally[TrialOutcome.PENDING],
            base_mismatch=tally[TrialExclusion.BASE_MISMATCH],
            treatment_mismatch=tally[TrialExclusion.TREATMENT_MISMATCH],
        )


@dataclass(frozen=True)
class CaseMetrics:
    """pass@k, pass^k and flakiness for one case of one cohort."""

    eval_id: str
    k: int
    counts: TrialCounts
    trials_short: int
    """max(0, k - judged - pending): in-flight trials are reserved. 0 once exhausted."""
    exhausted: bool
    """Infra errors reached k: advisory, the harness launches no more for this case."""
    pass_at_k: float | None
    """Conditional over judged trials; None while the case is short."""
    pass_hat_k: float | None
    flaky: bool | None
    pass_at_k_bounds: Bounds
    pass_hat_k_bounds: Bounds

    @property
    def complete(self) -> bool:
        """At least k judged trials: the case has a conditional metric."""
        return self.pass_hat_k is not None

    @property
    def never_launched(self) -> bool:
        return self.counts.launched == 0


def _bounds(counts: TrialCounts, k: int) -> tuple[Bounds, Bounds]:
    """(pass@k, pass^k) bounds with infra errors recoded; a short case is [0, 1]."""
    n, c, infra = counts.resolved, counts.passes, counts.infra_errors
    low_at, high_at = pass_at_k(n, c, k), pass_at_k(n, c + infra, k)
    low_hat, high_hat = pass_hat_k(n, c, k), pass_hat_k(n, c + infra, k)
    if low_at is None or high_at is None or low_hat is None or high_hat is None:
        return Bounds(0.0, 1.0), Bounds(0.0, 1.0)
    return Bounds(low_at, high_at), Bounds(low_hat, high_hat)


def case_metrics(eval_id: str, trials: Iterable[ClassifiedTrial], k: int) -> CaseMetrics:
    """The figures of one case in one cohort; ``trials`` are that case's trials in that cohort."""
    counts = TrialCounts.of(trials)
    exhausted = counts.infra_errors >= k
    short = 0 if exhausted else max(0, k - counts.judged - counts.pending)
    at = pass_at_k(counts.judged, counts.passes, k)
    hat = pass_hat_k(counts.judged, counts.passes, k)
    at_bounds, hat_bounds = _bounds(counts, k)
    return CaseMetrics(
        eval_id=eval_id,
        k=k,
        counts=counts,
        trials_short=short,
        exhausted=exhausted,
        pass_at_k=at,
        pass_hat_k=hat,
        flaky=None if at is None or hat is None else (at > 0 and hat < 1),
        pass_at_k_bounds=at_bounds,
        pass_hat_k_bounds=hat_bounds,
    )
