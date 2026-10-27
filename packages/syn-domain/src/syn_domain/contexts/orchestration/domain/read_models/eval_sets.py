"""An Eval Set's Roster and what each Cohort scored over it (#2108).

The Roster is the cases of one eval-set version, written onto the evals as
tags before anything is launched (plan section 5.1), so a case never launched
is a case with n = 0, never an absent one. Every figure is computed against
the roster:

- conditional means of pass@k and pass^k over the COMPLETE cases, labelled
  partial when any rostered case is not complete. Descriptive only;
- roster-wide bounds, where an infra error, a short case and a case never
  launched are 0 in the lower bound and 1 in the upper. Decisions read these.

Trials pool only within a cohort: a different suite version, workflow
version, declared model set or scoring protocol is another cohort, never the
same one (plan section 5.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
    ImageManifestState,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trial_metrics import (
    Bounds,
    CaseMetrics,
    case_metrics,
    require_k,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
    ClassifiedTrial,
    CohortKey,
    EvalTag,
    TrialExclusion,
    TrialOutcome,
    classify_trial,
    declared_models_of,
    single_tag,
    tag_values,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
        ImageManifestContent,
    )
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunFacts


@dataclass(frozen=True)
class TaggedEval:
    """An eval and its tags: what a roster is read from."""

    eval_id: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class RosterCase:
    eval_id: str
    split: str | None
    """None when the eval carries no split tag, or conflicting ones."""
    polarity: str | None
    """``defect`` or ``clean``; None when untagged or conflicting."""


@dataclass(frozen=True)
class Roster:
    """The cases of one eval-set version, optionally one split of it."""

    suite: str
    version: str
    split: str | None
    cases: tuple[RosterCase, ...]


def roster_of(
    evals: Iterable[TaggedEval], suite: str, version: str, split: str | None = None
) -> Roster:
    """The evals tagged ``suite:<suite>`` and ``suite-version:<version>``, in eval id order.

    Version tags accumulate (a case in v7 and v8 carries both); split never
    changes, so ``split`` is a filter on it.
    """
    cases = []
    for ev in sorted(evals, key=lambda e: e.eval_id):
        if suite not in tag_values(ev.tags, EvalTag.SUITE):
            continue
        if version not in tag_values(ev.tags, EvalTag.SUITE_VERSION):
            continue
        case = RosterCase(
            ev.eval_id,
            single_tag(ev.tags, EvalTag.SPLIT),
            single_tag(ev.tags, EvalTag.POLARITY),
        )
        if split is None or case.split == split:
            cases.append(case)
    return Roster(suite, version, split, tuple(cases))


def classify_roster_trials(
    roster: Roster,
    runs_by_eval: Mapping[str, Sequence[EvalRunFacts]],
    declared_models: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, list[ClassifiedTrial]]:
    """Every rostered case's member runs, classified.

    ``declared_models`` is keyed by models digest; when it is None each run is
    checked against the ``model:<phase>=<id>`` tags it launched with.
    """
    return {
        case.eval_id: [
            classify_trial(run, _declared(run, declared_models))
            for run in runs_by_eval.get(case.eval_id, ())
        ]
        for case in roster.cases
    }


def _declared(
    run: EvalRunFacts, declared_models: Mapping[str, Mapping[str, str]] | None
) -> Mapping[str, str] | None:
    if declared_models is None:
        return declared_models_of(run.inherited_tags)
    return declared_models.get(single_tag(run.inherited_tags, EvalTag.MODELS) or "")


@dataclass(frozen=True)
class CaseCohort:
    """One eval's figures in one cohort."""

    cohort: CohortKey
    metrics: CaseMetrics


def summarize_case(
    eval_id: str,
    runs: Iterable[EvalRunFacts],
    k: int,
    declared_models: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[CaseCohort, ...]:
    """One eval's figures in every cohort it has trials in, in key order.

    A run that is no trial (attached, launch tags missing) belongs to none.
    """
    require_k(k)
    roster = Roster("", "", None, (RosterCase(eval_id, None, None),))
    trials = classify_roster_trials(roster, {eval_id: list(runs)}, declared_models)[eval_id]
    cohorts = sorted({t.cohort for t in trials if t.cohort is not None})
    return tuple(CaseCohort(c, case_metrics(eval_id, in_cohort(trials, c), k)) for c in cohorts)


def in_cohort(trials: Iterable[ClassifiedTrial], cohort: CohortKey) -> list[ClassifiedTrial]:
    return [t for t in trials if t.cohort == cohort]


@dataclass(frozen=True)
class Coverage:
    """How much of the roster a cohort has judged."""

    roster_size: int
    complete: int
    short: int
    """Launched, but fewer than k judged trials."""
    never_launched: int


@dataclass(frozen=True)
class ImageProvenance:
    """Which workspace images a cohort's trials ran: one cohort may span several."""

    manifests: tuple[ImageManifestContent, ...]
    """Every distinct manifest a phase of a trial read, in a stable order."""
    trials_without_manifest: int
    """Trials no phase of which read a manifest: absent, unreadable, or never provisioned."""


def image_provenance(trials: Iterable[ClassifiedTrial]) -> ImageProvenance:
    """The images of the counted trials (``TrialOutcome``), not of excluded runs."""
    distinct: dict[str, ImageManifestContent] = {}
    without = 0
    for trial in trials:
        if not isinstance(trial.result, TrialOutcome):
            continue
        read = [
            m.manifest
            for m in trial.run.image_manifests
            if m.state is ImageManifestState.READ and m.manifest is not None
        ]
        if not read:
            without += 1
        for manifest in read:
            distinct.setdefault(manifest.model_dump_json(), manifest)
    return ImageProvenance(tuple(distinct[key] for key in sorted(distinct)), without)


@dataclass(frozen=True)
class CohortSummary:
    """One cohort's figures over one roster."""

    cohort: CohortKey
    k: int
    cases: tuple[CaseMetrics, ...]
    """One per rostered case, in roster order; a never-launched case has zero counts."""
    coverage: Coverage
    mean_pass_at_k: float | None
    """Over complete cases only; None when none is complete."""
    mean_pass_hat_k: float | None
    flakiness: float | None
    """mean pass@k - mean pass^k."""
    partial: bool
    """The means cover fewer than every rostered case: descriptive, never a decision."""
    flaky_cases: tuple[str, ...]
    pass_at_k_bounds: Bounds
    """Roster-wide: a short or never-launched case is 0 in the lower bound and 1 in the upper."""
    pass_hat_k_bounds: Bounds
    infra_error_count: int
    infra_share: float | None
    """Infra errors over resolved trials (judged + infra); None when nothing resolved."""
    base_mismatch_count: int
    treatment_mismatch_count: int
    images: ImageProvenance


@dataclass(frozen=True)
class EvalSetSummary:
    roster: Roster
    cohorts: tuple[CohortSummary, ...]
    not_a_trial_count: int
    """Member runs of rostered cases that belong to no cohort: attached, or launch tags missing."""
    trials: Mapping[str, Sequence[ClassifiedTrial]]
    """Every rostered case's member runs, classified: what a paired comparison reads."""


def _mean(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def summarize_cohort(
    roster: Roster, trials: Mapping[str, Sequence[ClassifiedTrial]], cohort: CohortKey, k: int
) -> CohortSummary:
    """One cohort over the whole roster; ``trials`` is ``classify_roster_trials`` output."""
    require_k(k)
    by_case = {c.eval_id: in_cohort(trials.get(c.eval_id, ()), cohort) for c in roster.cases}
    cases = tuple(case_metrics(c.eval_id, by_case[c.eval_id], k) for c in roster.cases)
    complete = [c for c in cases if c.complete]
    at = _mean([c.pass_at_k for c in complete if c.pass_at_k is not None])
    hat = _mean([c.pass_hat_k for c in complete if c.pass_hat_k is not None])
    infra = sum(c.counts.infra_errors for c in cases)
    resolved = sum(c.counts.resolved for c in cases)
    never = sum(1 for c in cases if c.never_launched)
    return CohortSummary(
        cohort=cohort,
        k=k,
        cases=cases,
        coverage=Coverage(len(cases), len(complete), len(cases) - len(complete) - never, never),
        mean_pass_at_k=at,
        mean_pass_hat_k=hat,
        flakiness=None if at is None or hat is None else at - hat,
        partial=len(complete) < len(cases),
        flaky_cases=tuple(c.eval_id for c in complete if c.flaky),
        pass_at_k_bounds=_roster_bounds([c.pass_at_k_bounds for c in cases]),
        pass_hat_k_bounds=_roster_bounds([c.pass_hat_k_bounds for c in cases]),
        infra_error_count=infra,
        infra_share=infra / resolved if resolved else None,
        base_mismatch_count=sum(c.counts.base_mismatch for c in cases),
        treatment_mismatch_count=sum(c.counts.treatment_mismatch for c in cases),
        images=image_provenance(t for ts in by_case.values() for t in ts),
    )


def _roster_bounds(per_case: Sequence[Bounds]) -> Bounds:
    if not per_case:
        return Bounds(0.0, 1.0)
    return Bounds(fmean(b.lower for b in per_case), fmean(b.upper for b in per_case))


def summarize_eval_set(
    roster: Roster,
    runs_by_eval: Mapping[str, Sequence[EvalRunFacts]],
    k: int,
    declared_models: Mapping[str, Mapping[str, str]] | None = None,
) -> EvalSetSummary:
    """Every cohort that launched into this roster version, one block each, in key order."""
    require_k(k)
    trials = classify_roster_trials(roster, runs_by_eval, declared_models)
    flat = [t for ts in trials.values() for t in ts]
    cohorts = sorted(
        {
            t.cohort
            for t in flat
            if t.cohort is not None and t.cohort.suite_version == roster.version
        }
    )
    return EvalSetSummary(
        roster=roster,
        cohorts=tuple(summarize_cohort(roster, trials, c, k) for c in cohorts),
        not_a_trial_count=sum(1 for t in flat if t.result is TrialExclusion.NOT_A_TRIAL),
        trials=trials,
    )
