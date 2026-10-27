"""What one run of an eval counts as: a Trial, its Cohort and its Trial Outcome (#2108).

A Trial is a run LAUNCHED into an eval; an attached run is a member, not a
trial. Its Cohort is read from the run's launch tags (``inherited_tags``),
never from its editable tags, so retagging a run cannot move it between
cohorts. Its Trial Outcome is derived at read time by one ordered rule
(``classify_trial``, plan section 6) from facts that are already Lane 1 truth:
status, failure classification, the starting checkout against the eval's
baseline, and the current score. Nothing here is stored, so a re-score or a
re-classification changes the outcome on the next read with no migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import (
        EvalRunFacts,
        EvalRunScore,
    )


class EvalTag(StrEnum):
    """The tag prefixes an eval set is read from; a tag is ``<prefix>:<value>``."""

    SUITE = "suite"
    SUITE_VERSION = "suite-version"
    SPLIT = "split"
    POLARITY = "polarity"
    MODELS = "models"
    """sha256 of the suite's declared models map: declared, so an early failure still joins."""
    SCORER = "scorer"
    """The scoring protocol id: a different judge is a different ruler."""
    TRIAL = "trial"


def tag_values(tags: Iterable[str], prefix: EvalTag) -> frozenset[str]:
    """Every value tagged ``<prefix>:<value>``."""
    head = f"{prefix}:"
    return frozenset(t.removeprefix(head) for t in tags if t.startswith(head))


def single_tag(tags: Iterable[str], prefix: EvalTag) -> str | None:
    """The one value of ``prefix``; None when it is missing or conflicting."""
    values = tag_values(tags, prefix)
    return next(iter(values)) if len(values) == 1 else None


@dataclass(frozen=True, order=True)
class CohortKey:
    """The trials of one roster that share a declared treatment and scoring protocol."""

    suite_version: str
    workflow_id: str
    workflow_version: str
    """``""`` when unrecorded: unrecorded runs group together, as variants do."""
    models_digest: str
    scorer_protocol: str


class TrialOutcome(StrEnum):
    """What a trial says about the agent. Distinct from the scorer's Verdict."""

    PASS = "pass"
    FAIL = "fail"
    INFRA_ERROR = "infra_error"
    """The result says nothing about the agent: out of n, a fail in the lower bound."""
    PENDING = "pending"
    """Running, or completed and not yet scored under the cohort's protocol."""


class TrialExclusion(StrEnum):
    """Why a member run is not counted as a trial. Exclusions are counted, never dropped."""

    NOT_A_TRIAL = "not_a_trial"
    BASE_MISMATCH = "base_mismatch"
    TREATMENT_MISMATCH = "treatment_mismatch"


@dataclass(frozen=True)
class ClassifiedTrial:
    """One member run, read as a trial of its cohort, or as an exclusion."""

    run: EvalRunFacts
    cohort: CohortKey | None
    """None only for ``NOT_A_TRIAL``: a run with no cohort belongs to none."""
    result: TrialOutcome | TrialExclusion


def cohort_of(run: EvalRunFacts) -> CohortKey | None:
    """The run's cohort from its launch tags; None when any part is missing or conflicting."""
    tags = run.inherited_tags
    version = single_tag(tags, EvalTag.SUITE_VERSION)
    models = single_tag(tags, EvalTag.MODELS)
    scorer = single_tag(tags, EvalTag.SCORER)
    if version is None or models is None or scorer is None:
        return None
    return CohortKey(version, run.workflow_id, run.workflow_version or "", models, scorer)


def _base_mismatch(run: EvalRunFacts) -> bool:
    """A checkout IS recorded and is not the baseline. An absent checkout never mismatches."""
    if not run.starting_checkout:
        return False
    checked_out = {c.repository: c.sha for c in run.starting_checkout}
    pinned = {p.repository: p.commit_sha for p in run.baseline}
    return checked_out != pinned


def _treatment_mismatch(run: EvalRunFacts, declared: Mapping[str, str]) -> bool:
    """A phase's own observed model contradicts its declared id. A silent phase never does."""
    return any(declared.get(m.phase_id, m.model) != m.model for m in run.own_models)


def _current_score(run: EvalRunFacts, cohort: CohortKey) -> EvalRunScore | None:
    """The score, if it was made under the cohort's protocol; else the trial is unscored."""
    score = run.score
    if score is None or score.scorer_version != cohort.scorer_protocol:
        return None
    return score


_VERDICT_OUTCOME = {
    Verdict.PASS: TrialOutcome.PASS,
    Verdict.FAIL: TrialOutcome.FAIL,
    # #1780: completed with no recorded review verdict is the engine's gap, or the scorer broke.
    Verdict.ERROR: TrialOutcome.INFRA_ERROR,
}

_AGENT_STOPPED = frozenset({FailureClassification.CORRECT_REFUSAL, FailureClassification.TASK})


def _outcome(run: EvalRunFacts, cohort: CohortKey) -> TrialOutcome:
    """Rows 4 to 12 of the ordered rule, for a run already known to be a trial."""
    status = run.status
    if status in (ExecutionStatus.NOT_STARTED, ExecutionStatus.RUNNING):
        return TrialOutcome.PENDING
    if status in (ExecutionStatus.CANCELLED, ExecutionStatus.INTERRUPTED):
        return TrialOutcome.INFRA_ERROR
    if status == ExecutionStatus.FAILED:
        # The agent stopped without the deliverable, whatever the score says.
        if run.failure_classification in _AGENT_STOPPED:
            return TrialOutcome.FAIL
        # platform, unclassified, or never classified: includes failures before
        # provisioning, which record no checkout.
        return TrialOutcome.INFRA_ERROR
    if status != ExecutionStatus.COMPLETED:
        return TrialOutcome.INFRA_ERROR
    if not run.starting_checkout:
        # A result on an unverified base is not judged.
        return TrialOutcome.INFRA_ERROR
    score = _current_score(run, cohort)
    if score is None:
        return TrialOutcome.PENDING
    return _VERDICT_OUTCOME[score.verdict]


def classify_trial(
    run: EvalRunFacts, declared_models: Mapping[str, str] | None = None
) -> ClassifiedTrial:
    """The ordered rule of plan section 6: the first matching row wins.

    ``declared_models`` maps phase id to the explicit model id the cohort
    declared; when it is None the treatment check (row 3) is not applied.
    """
    cohort = cohort_of(run)
    if run.association_kind is not AssociationKind.LAUNCHED or cohort is None:
        return ClassifiedTrial(run, None, TrialExclusion.NOT_A_TRIAL)
    if _base_mismatch(run):
        return ClassifiedTrial(run, cohort, TrialExclusion.BASE_MISMATCH)
    if declared_models is not None and _treatment_mismatch(run, declared_models):
        return ClassifiedTrial(run, cohort, TrialExclusion.TREATMENT_MISMATCH)
    return ClassifiedTrial(run, cohort, _outcome(run, cohort))
