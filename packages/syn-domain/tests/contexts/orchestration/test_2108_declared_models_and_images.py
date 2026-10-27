"""#2108 S2 domain reads: declared models from launch tags, per-eval cohorts, images, the pair."""

from __future__ import annotations

from dataclasses import replace

import pytest

from syn_domain.contexts.orchestration._shared.tags import MAX_TAG_LENGTH, TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import PhaseModel
from syn_domain.contexts.orchestration.domain.read_models.eval_set_comparison import (
    compare_pair,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_sets import (
    TaggedEval,
    roster_of,
    summarize_case,
    summarize_eval_set,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
    DeclaredModel,
    TrialExclusion,
    cohort_of,
    declared_model_tags,
    declared_models_of,
    models_digest,
)

from .eval_trial_builders import OTHER_SHA, PROTOCOL, REPO, cohort, cohort_tags, run

pytestmark = pytest.mark.unit

OPUS = "claude-opus-5-5"
SOL = "gpt-6.1-sol"


def _with_models(*declared: str) -> tuple[str, ...]:
    return (*cohort_tags(), *(f"model:{d}" for d in declared))


def test_declared_models_are_read_per_phase() -> None:
    assert declared_models_of(_with_models(f"build:{OPUS}", f"verify:{SOL}")) == {
        "build": OPUS,
        "verify": SOL,
    }


def _declared(**models: str) -> list[DeclaredModel]:
    return [DeclaredModel(phase, model) for phase, model in models.items()]


def test_declared_model_tags_survive_the_launch_tag_rules_and_read_back() -> None:
    """The writer's tags pass TagSet (what every execute request validates through) unchanged."""
    models = _declared(verify=SOL, **{"implement-and-self-review": OPUS})
    written = [*cohort_tags()[:1], f"scorer:{PROTOCOL}", *declared_model_tags(models)]

    launched = list(TagSet(written))

    assert sorted(launched) == sorted(written)
    assert max(len(t) for t in launched) <= MAX_TAG_LENGTH
    assert declared_models_of(launched) == {m.phase_id: m.model for m in models}
    key = cohort_of(run(tags=tuple(launched)))
    assert key is not None and key.models_digest == models_digest(models)


def test_the_models_digest_ignores_order_and_sees_every_phase() -> None:
    assert models_digest(_declared(a=OPUS, b=SOL)) == models_digest(_declared(b=SOL, a=OPUS))
    assert models_digest(_declared(a=OPUS)) != models_digest(_declared(a=OPUS, b=SOL))
    assert models_digest(_declared(a=OPUS, b=SOL)) != models_digest(_declared(a=SOL, b=OPUS))


def test_no_model_tags_declare_nothing_so_no_check_applies() -> None:
    assert declared_models_of(cohort_tags()) is None


def test_a_phase_declared_twice_differently_can_never_match() -> None:
    declared = declared_models_of(_with_models(f"build:{OPUS}", f"build:{SOL}"))

    assert declared == {"build": ""}


def test_a_malformed_model_tag_is_not_a_declaration() -> None:
    assert declared_models_of(_with_models("build", ":x", "build:")) is None


def test_a_set_checks_each_trial_against_the_models_it_launched_with() -> None:
    roster = roster_of([TaggedEval("eval-1", ("suite:s", "suite-version:1"))], "s", "1")
    matched = run(tags=_with_models(f"build:{OPUS}"), own_models=(PhaseModel("build", OPUS),))
    swapped = run(tags=_with_models(f"build:{OPUS}"), own_models=(PhaseModel("build", SOL),))

    summary = summarize_eval_set(roster, {"eval-1": [matched, swapped]}, k=1)

    (block,) = summary.cohorts
    assert block.treatment_mismatch_count == 1
    assert block.cases[0].counts.passes == 1


def test_one_eval_reports_every_cohort_it_has_trials_in() -> None:
    v1 = [run(Verdict.PASS), run(Verdict.FAIL)]
    v2 = [run(Verdict.PASS, tags=cohort_tags(version="2"))]
    attached_like = run(tags=())

    cases = summarize_case("eval-1", [*v1, *v2, attached_like], k=2)

    assert [(c.cohort, c.metrics.counts.judged) for c in cases] == [
        (cohort("1"), 2),
        (cohort("2"), 1),
    ]
    assert cases[0].metrics.pass_at_k == 1.0
    assert cases[1].metrics.trials_short == 1


def _manifest(build_commit: str) -> ImageManifestReading:
    return ImageManifestReading(
        state=ImageManifestState.READ,
        manifest=ImageManifestContent(
            provider="claude",
            provider_version="2.1.0",
            components={},
            build_commit=build_commit,
            built_at="2026-10-27T00:00:00Z",
            manifest_digest="d" * 64,
        ),
    )


def test_a_cohort_lists_its_distinct_images_and_counts_trials_without_one() -> None:
    roster = roster_of([TaggedEval("eval-1", ("suite:s", "suite-version:1"))], "s", "1")
    elsewhere = (SourceCommit(repository=REPO, sha=OTHER_SHA),)
    runs = [
        replace(run(), image_manifests=(_manifest("c1"), _manifest("c1"))),
        replace(run(), image_manifests=(_manifest("c2"),)),
        replace(run(), image_manifests=(ImageManifestReading.absent(),)),
        run(),
        # An excluded run is not a trial: its image says nothing about the cohort.
        replace(run(checkout=elsewhere), image_manifests=(_manifest("c9"),)),
    ]

    summary = summarize_eval_set(roster, {"eval-1": runs}, k=1)

    (block,) = summary.cohorts
    assert [m.build_commit for m in block.images.manifests] == ["c1", "c2"]
    assert block.images.trials_without_manifest == 2
    assert block.base_mismatch_count == 1


def test_two_cohorts_are_paired_and_one_or_three_are_not() -> None:
    roster = roster_of([TaggedEval("eval-1", ("suite:s", "suite-version:1"))], "s", "1")
    a = run(Verdict.PASS)
    b = run(Verdict.FAIL, tags=cohort_tags(scorer="other"), scorer_version="other")
    c = run(Verdict.FAIL, tags=cohort_tags(scorer="third"), scorer_version="third")

    one = summarize_eval_set(roster, {"eval-1": [a]}, k=1)
    two = summarize_eval_set(roster, {"eval-1": [a, b]}, k=1)
    three = summarize_eval_set(roster, {"eval-1": [a, b, c]}, k=1)

    assert compare_pair(one) is None
    assert compare_pair(three) is None
    pair = compare_pair(two)
    assert pair is not None
    assert (pair.a, pair.b) == (two.cohorts[0].cohort, two.cohorts[1].cohort)
    assert pair.paired_cases == ("eval-1",)


def test_an_excluded_trial_result_is_an_exclusion() -> None:
    roster = roster_of([TaggedEval("eval-1", ("suite:s", "suite-version:1"))], "s", "1")
    attached = run(tags=())

    summary = summarize_eval_set(roster, {"eval-1": [attached]}, k=1)

    assert summary.trials["eval-1"][0].result is TrialExclusion.NOT_A_TRIAL
    assert summary.not_a_trial_count == 1
