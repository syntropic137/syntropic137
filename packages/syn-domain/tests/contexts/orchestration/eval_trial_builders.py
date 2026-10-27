"""Builders for #2108 trial tests: one launched, provisioned, scored run unless told otherwise."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    EvalBaselinePin,
    ExecutionStatus,
    FailureClassification,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import (
    EvalRunFacts,
    EvalRunScore,
    PhaseModel,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import CohortKey

REPO = "syntropic137/syntropic137"
PIN = "a" * 40
OTHER_SHA = "b" * 40
PROTOCOL = "keyword-v1"
MODELS = "m" * 32
WORKFLOW = "verify-v1"
BASELINE = (EvalBaselinePin(repository=REPO, requested_ref="main", commit_sha=PIN),)
CHECKOUT = (SourceCommit(repository=REPO, sha=PIN),)


def cohort_tags(
    version: str = "1", models: str = MODELS, scorer: str = PROTOCOL
) -> tuple[str, ...]:
    return (f"suite-version:{version}", f"models:{models}", f"scorer:{scorer}", "trial:b1/0")


def cohort(version: str = "1", scorer: str = PROTOCOL, models: str = MODELS) -> CohortKey:
    return CohortKey(version, WORKFLOW, "v1", models, scorer)


_counter = iter(range(1_000_000))
_EPOCH = datetime(2026, 10, 27, tzinfo=UTC)


def run(
    verdict: Verdict | None = Verdict.PASS,
    *,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    classification: FailureClassification | None = None,
    kind: AssociationKind | None = AssociationKind.LAUNCHED,
    tags: tuple[str, ...] | None = None,
    checkout: tuple[SourceCommit, ...] = CHECKOUT,
    scorer_version: str = PROTOCOL,
    own_models: tuple[PhaseModel, ...] = (),
    started_at: str | None = None,
    eval_id: str = "eval-1",
) -> EvalRunFacts:
    n = next(_counter)
    execution_id = f"exec-{n:06d}"
    score = (
        None
        if verdict is None
        else EvalRunScore(
            eval_id=eval_id,
            execution_id=execution_id,
            verdict=verdict,
            scorer="eval_suite.py",
            scorer_version=scorer_version,
            scored_at="2026-10-27T00:00:00Z",
        )
    )
    return EvalRunFacts(
        execution_id=execution_id,
        workflow_id=WORKFLOW,
        workflow_version="v1",
        status=status,
        started_at=started_at or (_EPOCH + timedelta(seconds=n)).isoformat(),
        completed_at=None,
        models=own_models,
        total_cost_usd=None,
        duration_seconds=None,
        score=score,
        own_models=own_models,
        failure_classification=classification,
        association_kind=kind,
        inherited_tags=cohort_tags() if tags is None else tags,
        starting_checkout=checkout,
        baseline=BASELINE,
    )
