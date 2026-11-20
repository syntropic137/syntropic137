"""One sum over ``ExecutionCost`` rows for every cost surface (issue #897).

``/insights/cost``, ``/repos/{id}/cost`` and ``/systems/{id}/cost`` all answer
"what did this set of executions cost, and how much of it could not be
priced". They used to answer it from three sources that disagreed: a Timescale
``SUM`` that skips rows with no vendor cost, and ``RepoCost`` payload totals
with no coverage at all. Callers now choose WHICH executions; this module
alone decides how they add up, so the three totals cannot drift apart again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from syn_api.model_identity import cost_by_observed_model_text
from syn_shared.display.formatters import format_cost

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
        ExecutionCost,
    )
    from syn_domain.contexts.organization import CorrelatedExecution


@dataclass(frozen=True)
class CostRollup:
    """Money, coverage and tokens for a set of executions, ready for a response.

    Coverage travels with the money: a total summed without its unpriced count
    reads as complete when it is only a lower bound (#890, #897).
    """

    total_cost_usd: str
    total_cost_display: str
    unpriced_observation_count: int
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    cost_by_repo: dict[str, str]
    cost_by_workflow: dict[str, str]
    unpriced_by_workflow: dict[str, int]
    cost_by_model: dict[str, str]
    execution_count: int


@dataclass
class _Totals:
    cost: Decimal = Decimal("0")
    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    unpriced: int = 0
    by_repo: dict[str, Decimal] = field(default_factory=dict)
    by_workflow: dict[str, Decimal] = field(default_factory=dict)
    unpriced_by_workflow: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, Decimal] = field(default_factory=dict)


def roll_up_costs(
    costs: Sequence[ExecutionCost],
    *,
    correlated: Mapping[str, CorrelatedExecution] | None = None,
) -> CostRollup:
    """Sum ``costs`` into totals and breakdowns.

    ``correlated`` is the repo correlation of the scoped executions. When given:

    - ``cost_by_repo`` attributes each execution's cost to EVERY repo it is
      correlated with, so the buckets can sum to more than the total when one
      execution touched two repos. The totals count each execution once.
    - an execution whose ``ExecutionCost`` carries no ``workflow_id`` (the
      Timescale builders do not read one) is attributed to the workflow its
      correlation recorded.

    An execution it does not name is left out of those breakdowns only, never
    out of the totals.
    """
    t = _Totals()
    for c in costs:
        t.cost += c.total_cost_usd
        t.input += c.input_tokens
        t.output += c.output_tokens
        t.cache_creation += c.cache_creation_tokens
        t.cache_read += c.cache_read_tokens
        t.unpriced += c.unpriced_observation_count
        correlation = correlated.get(c.execution_id) if correlated is not None else None
        for repo in sorted(correlation.repos) if correlation else ():
            t.by_repo[repo] = t.by_repo.get(repo, Decimal("0")) + c.total_cost_usd
        workflow_id = c.workflow_id or (correlation.workflow_id if correlation else None)
        if workflow_id:
            t.by_workflow[workflow_id] = (
                t.by_workflow.get(workflow_id, Decimal("0")) + c.total_cost_usd
            )
            if c.unpriced_observation_count:
                t.unpriced_by_workflow[workflow_id] = (
                    t.unpriced_by_workflow.get(workflow_id, 0) + c.unpriced_observation_count
                )
        for model, model_cost in c.cost_by_model.items():
            t.by_model[model] = t.by_model.get(model, Decimal("0")) + model_cost

    return CostRollup(
        total_cost_usd=str(t.cost),
        total_cost_display=format_cost(t.cost, t.unpriced),
        unpriced_observation_count=t.unpriced,
        # All four components (issue #873) - matches the executions read model.
        total_tokens=t.input + t.output + t.cache_creation + t.cache_read,
        total_input_tokens=t.input,
        total_output_tokens=t.output,
        total_cache_creation_tokens=t.cache_creation,
        total_cache_read_tokens=t.cache_read,
        cost_by_repo={k: str(v) for k, v in t.by_repo.items()},
        cost_by_workflow={k: str(v) for k, v in t.by_workflow.items()},
        unpriced_by_workflow=t.unpriced_by_workflow,
        cost_by_model=cost_by_observed_model_text(t.by_model),
        execution_count=len(costs),
    )
