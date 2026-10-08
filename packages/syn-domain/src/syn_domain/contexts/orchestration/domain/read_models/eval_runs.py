"""Read models for an Eval's runs, their scores, and its variants (Evals v2).

A RUN is an execution that is currently a member of the eval; its facts stay
in the execution read models. What the eval read model adds is the run's
SCORE, from ``EvalRunScored``. The rest of a run's row - the models its phases
actually ran and what it cost - is Lane 2 telemetry, joined at read time by
the caller, so ``EvalRunFacts`` is what that caller hands back.

``summarize`` is the one place pass rate, variants and their duration and
cost figures are decided, so the eval list, the eval detail and the runs view
cannot count differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class EvalRunScore(BaseModel):
    """A run's current score: the latest ``EvalRunScored`` for (eval, execution).

    Also the stored document, written with ``model_dump(mode="json")``.
    """

    model_config = ConfigDict(frozen=True)

    eval_id: str
    execution_id: str
    verdict: Verdict
    score: float | None = None
    evidence: str = ""
    scorer: str
    scorer_version: str
    scored_at: str
    """ISO 8601 UTC."""


@dataclass(frozen=True)
class PhaseModel:
    """The model one phase ACTUALLY ran, as reported by its harness. Never an alias."""

    phase_id: str
    model: str


@dataclass(frozen=True)
class EvalRunFacts:
    """One run of an eval, with its Lane 2 facts and its score if it has one."""

    execution_id: str
    workflow_id: str
    workflow_version: str | None
    """The installed version or source digest the run launched from; None if unrecorded."""
    status: str
    started_at: str | None
    completed_at: str | None
    models: tuple[PhaseModel, ...]
    total_cost_usd: Decimal | None
    """``None`` when the run's cost could not be read, not when it was free."""
    duration_seconds: float | None
    score: EvalRunScore | None

    @property
    def variant_models(self) -> tuple[str, ...]:
        """Sorted, unique observed models: what makes two runs the same variant."""
        return tuple(sorted({m.model for m in self.models}))


@dataclass(frozen=True)
class EvalRunStats:
    """How long a set of runs took and what it cost, over EVERY run in the set.

    Medians, not means: one runaway run should not make a variant look slow.
    """

    median_duration_seconds: float | None
    """Over the runs whose duration is known; ``None`` when none is."""
    median_cost_usd: Decimal | None
    """Over the runs whose cost is known; ``None`` when none is."""
    cost_per_pass_usd: Decimal | None
    """Known spend of every run (FAIL, ERROR and unscored included) over PASS runs.

    What one passing run costs once the runs that did not pass are paid for.
    ``None`` when nothing passed or no cost is known: not infinite, not zero.
    """
    unknown_cost_count: int
    """Runs whose cost could not be read, so ``cost_per_pass_usd`` is a lower bound."""


@dataclass(frozen=True)
class EvalVariant:
    """Every run of the eval with the same workflow, workflow version and observed models."""

    workflow_id: str
    workflow_version: str | None
    """The installed version or source digest the runs launched from; None if unrecorded."""
    models: tuple[str, ...]
    run_count: int
    pass_count: int
    pass_rate: float | None
    """PASS over PASS + FAIL; ``None`` when neither. ERROR is not a verdict on the work."""
    avg_cost_usd: Decimal | None
    """Mean over the runs whose cost is known; ``None`` when none is."""
    last_run_at: str | None
    last_verdict: Verdict | None
    """The verdict of this variant's newest run that has one."""
    stats: EvalRunStats


@dataclass(frozen=True)
class EvalRunsSummary:
    """What an eval's runs add up to, on every eval row."""

    run_count: int
    scored_count: int
    pass_rate: float | None
    last_run_at: str | None
    last_verdict: Verdict | None
    """The verdict of the newest run that has one."""
    variants: tuple[EvalVariant, ...]
    stats: EvalRunStats


def _pass_rate(runs: Sequence[EvalRunFacts]) -> tuple[int, int, float | None]:
    """Scored count (every verdict), PASS count, and PASS over PASS + FAIL.

    ERROR is a run that could not be judged (a provision failure, say), so it
    counts as scored but stays out of the rate: it is neither a pass nor a fail.
    """
    scored = [r.score for r in runs if r.score is not None]
    passed = sum(1 for s in scored if s.verdict is Verdict.PASS)
    judged = sum(1 for s in scored if s.verdict is not Verdict.ERROR)
    return len(scored), passed, (passed / judged) if judged else None


def _stats(runs: Sequence[EvalRunFacts], passed: int) -> EvalRunStats:
    durations = [r.duration_seconds for r in runs if r.duration_seconds is not None]
    costs = [r.total_cost_usd for r in runs if r.total_cost_usd is not None]
    return EvalRunStats(
        median_duration_seconds=median(durations) if durations else None,
        median_cost_usd=median(costs) if costs else None,
        cost_per_pass_usd=sum(costs, Decimal(0)) / passed if costs and passed else None,
        unknown_cost_count=len(runs) - len(costs),
    )


def _last_verdict(ordered: Iterable[EvalRunFacts]) -> Verdict | None:
    """The verdict of the first run that has one; ``ordered`` is newest first."""
    return next((r.score.verdict for r in ordered if r.score is not None), None)


def _newest_first(runs: Iterable[EvalRunFacts]) -> list[EvalRunFacts]:
    return sorted(runs, key=lambda r: (r.started_at or "", r.execution_id), reverse=True)


def summarize(runs: Iterable[EvalRunFacts]) -> EvalRunsSummary:
    """Run count, pass rate, newest verdict, duration and cost of one eval's runs and its variants."""
    ordered = _newest_first(runs)
    scored_count, total_passed, pass_rate = _pass_rate(ordered)
    # The version is part of the key: a workflow edited between two runs is a
    # different treatment, and pooling them would hide the change being measured.
    # An unrecorded version sorts as "" and groups with the other unrecorded runs.
    groups: dict[tuple[str, str, tuple[str, ...]], list[EvalRunFacts]] = {}
    for run in ordered:
        key = (run.workflow_id, run.workflow_version or "", run.variant_models)
        groups.setdefault(key, []).append(run)
    variants = []
    for (workflow_id, _version, models), members in sorted(groups.items()):
        _, passed, rate = _pass_rate(members)
        costs = [r.total_cost_usd for r in members if r.total_cost_usd is not None]
        variants.append(
            EvalVariant(
                workflow_id=workflow_id,
                workflow_version=members[0].workflow_version,
                models=models,
                run_count=len(members),
                pass_count=passed,
                pass_rate=rate,
                avg_cost_usd=sum(costs, Decimal(0)) / len(costs) if costs else None,
                last_run_at=members[0].started_at,
                last_verdict=_last_verdict(members),
                stats=_stats(members, passed),
            )
        )
    return EvalRunsSummary(
        run_count=len(ordered),
        scored_count=scored_count,
        pass_rate=pass_rate,
        last_run_at=ordered[0].started_at if ordered else None,
        last_verdict=_last_verdict(ordered),
        variants=tuple(variants),
        stats=_stats(ordered, total_passed),
    )
