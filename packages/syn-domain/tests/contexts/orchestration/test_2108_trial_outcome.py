"""The ordered Trial Outcome rule (#2108, plan section 6): T1 and T1b.

T1 crosses every status (and every failure classification) with every score
(absent, PASS, FAIL, ERROR) and with the checkout recorded or absent, and
pins each cell to the row of the plan's table that decides it. The expected
cells are written out, not recomputed, so a change to the rule has to change
this table too.
"""

from __future__ import annotations

import itertools

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import PhaseModel
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
    TrialExclusion,
    TrialOutcome,
    classify_trial,
    cohort_of,
)

from .eval_trial_builders import (
    CHECKOUT,
    MODELS,
    OTHER_SHA,
    PROTOCOL,
    REPO,
    cohort,
    cohort_tags,
    run,
)

pytestmark = pytest.mark.unit

S = ExecutionStatus
F = FailureClassification
P, FL, IE, PD = (
    TrialOutcome.PASS,
    TrialOutcome.FAIL,
    TrialOutcome.INFRA_ERROR,
    TrialOutcome.PENDING,
)
SCORES = (None, Verdict.PASS, Verdict.FAIL, Verdict.ERROR)

# (status, classification) -> outcome by score (absent, PASS, FAIL, ERROR),
# first with the checkout recorded, then with it absent.
TABLE: dict[tuple[S, F | None], tuple[tuple[TrialOutcome, ...], tuple[TrialOutcome, ...]]] = {
    (S.NOT_STARTED, None): ((PD, PD, PD, PD), (PD, PD, PD, PD)),  # row 4
    (S.RUNNING, None): ((PD, PD, PD, PD), (PD, PD, PD, PD)),  # row 4
    (S.CANCELLED, None): ((IE, IE, IE, IE), (IE, IE, IE, IE)),  # row 5
    (S.INTERRUPTED, None): ((IE, IE, IE, IE), (IE, IE, IE, IE)),  # row 5
    (S.FAILED, F.TASK): ((FL, FL, FL, FL), (FL, FL, FL, FL)),  # row 6
    (S.FAILED, F.CORRECT_REFUSAL): ((FL, FL, FL, FL), (FL, FL, FL, FL)),  # row 6
    (S.FAILED, F.PLATFORM): ((IE, IE, IE, IE), (IE, IE, IE, IE)),  # row 7
    (S.FAILED, F.UNCLASSIFIED): ((IE, IE, IE, IE), (IE, IE, IE, IE)),  # row 7
    (S.FAILED, None): ((IE, IE, IE, IE), (IE, IE, IE, IE)),  # row 7, never classified
    # rows 9-12 with a checkout; row 8 without one
    (S.COMPLETED, None): ((PD, P, FL, IE), (IE, IE, IE, IE)),
}

CASES = [
    (
        status,
        classification,
        verdict,
        recorded,
        TABLE[status, classification][0 if recorded else 1][i],
    )
    for (status, classification), (i, verdict), recorded in itertools.product(
        TABLE, enumerate(SCORES), (True, False)
    )
]


def test_the_table_covers_every_status_and_every_failure_classification() -> None:
    assert {s for s, _ in TABLE} == set(ExecutionStatus)
    assert {c for s, c in TABLE if s is S.FAILED} == {*FailureClassification, None}


@pytest.mark.parametrize(("status", "classification", "verdict", "recorded", "expected"), CASES)
def test_t1_every_status_score_and_checkout_has_one_outcome(
    status: ExecutionStatus,
    classification: FailureClassification | None,
    verdict: Verdict | None,
    recorded: bool,
    expected: TrialOutcome,
) -> None:
    checkout = CHECKOUT if recorded else ()
    trial = classify_trial(
        run(verdict, status=status, classification=classification, checkout=checkout)
    )
    assert trial.result is expected
    assert trial.cohort == cohort()


def test_t1_an_attached_run_is_not_a_trial_whatever_its_score() -> None:
    trial = classify_trial(run(Verdict.PASS, kind=AssociationKind.ATTACHED))
    assert trial.result is TrialExclusion.NOT_A_TRIAL
    assert trial.cohort is None


def test_t1_a_run_with_no_membership_kind_is_not_a_trial() -> None:
    assert classify_trial(run(kind=None)).result is TrialExclusion.NOT_A_TRIAL


@pytest.mark.parametrize(
    "tags",
    [
        (),
        cohort_tags()[1:],  # no suite-version
        (*cohort_tags(), "suite-version:2"),  # conflicting
        (*cohort_tags(), "scorer:other-v2"),  # conflicting protocol
        ("suite-version:1", f"scorer:{PROTOCOL}"),  # no models
    ],
)
def test_t1_missing_or_conflicting_cohort_tags_make_it_not_a_trial(tags: tuple[str, ...]) -> None:
    assert classify_trial(run(tags=tags)).result is TrialExclusion.NOT_A_TRIAL


@pytest.mark.parametrize(
    "checkout",
    [
        (SourceCommit(repository=REPO, sha=OTHER_SHA),),
        (SourceCommit(repository=REPO, sha=None),),
        (SourceCommit(repository="other/repo", sha=OTHER_SHA),),
    ],
)
def test_t1_a_recorded_checkout_off_the_baseline_is_a_base_mismatch(
    checkout: tuple[SourceCommit, ...],
) -> None:
    # Even a PASS: membership alone never makes a trial.
    assert (
        classify_trial(run(Verdict.PASS, checkout=checkout)).result is TrialExclusion.BASE_MISMATCH
    )


def test_t1_a_base_mismatch_outranks_a_failed_status() -> None:
    bad = (SourceCommit(repository=REPO, sha=OTHER_SHA),)
    trial = run(None, status=S.FAILED, classification=F.TASK, checkout=bad)
    assert classify_trial(trial).result is TrialExclusion.BASE_MISMATCH


def test_t1_an_observed_model_off_its_declaration_is_a_treatment_mismatch() -> None:
    observed = (PhaseModel("verify", "claude-sonnet-5-5"),)
    trial = run(Verdict.PASS, own_models=observed)
    assert (
        classify_trial(trial, {"verify": "claude-opus-5-5"}).result
        is TrialExclusion.TREATMENT_MISMATCH
    )
    assert classify_trial(trial, {"verify": "claude-sonnet-5-5"}).result is TrialOutcome.PASS
    # Without a declaration the check is not applied.
    assert classify_trial(trial).result is TrialOutcome.PASS


def test_t1_a_phase_that_never_reported_a_model_is_not_a_mismatch() -> None:
    trial = run(None, status=S.FAILED, classification=F.PLATFORM, own_models=())
    assert classify_trial(trial, {"verify": "claude-opus-5-5"}).result is TrialOutcome.INFRA_ERROR


def test_t1_a_score_under_another_protocol_leaves_the_trial_unscored() -> None:
    trial = run(Verdict.PASS, scorer_version="llm-judge-v3")
    assert classify_trial(trial).result is TrialOutcome.PENDING


def test_t1b_cohort_identity_is_read_from_launch_tags_only() -> None:
    # A retag edits `tags`, which EvalRunFacts does not carry: identity is
    # inherited_tags. Tags with other prefixes never move a trial either.
    launched = run(tags=(*cohort_tags(), "verifier:verify-v1", "owner:someone"))
    assert cohort_of(launched) == cohort()
    assert cohort_of(launched) == cohort_of(run())
    assert cohort().models_digest == MODELS


def test_t1_an_observed_phase_with_no_declaration_is_a_treatment_mismatch() -> None:
    # Codex #2116: an undeclared phase could otherwise run any model and pass.
    trial = run(Verdict.PASS, own_models=(PhaseModel("review", "claude-sonnet-5-5"),))
    result = classify_trial(trial, {"verify": "claude-opus-5-5"}).result
    assert result is TrialExclusion.TREATMENT_MISMATCH
