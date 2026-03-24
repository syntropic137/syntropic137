"""Usage summary builder for spend tracking.

Extracted from SpendTracker to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_tokens.models import SpendBudget


def build_usage_summary(execution_id: str, budget: SpendBudget) -> dict[str, Any]:
    """Build a usage summary dict from a spend budget.

    Args:
        execution_id: Execution identifier.
        budget: The spend budget to summarize.

    Returns:
        Dictionary with usage stats.
    """
    return {
        "execution_id": execution_id,
        "workflow_type": budget.workflow_type.value,
        "input_tokens": {
            "used": budget.used_input_tokens,
            "max": budget.max_input_tokens,
            "remaining": budget.remaining_input_tokens,
            "percent": budget.input_usage_percent,
        },
        "output_tokens": {
            "used": budget.used_output_tokens,
            "max": budget.max_output_tokens,
            "remaining": budget.remaining_output_tokens,
            "percent": budget.output_usage_percent,
        },
        "cost_usd": {
            "used": str(budget.used_cost_usd),
            "max": str(budget.max_cost_usd),
            "remaining": str(budget.remaining_cost_usd),
            "percent": budget.cost_usage_percent,
        },
        "is_exhausted": budget.is_exhausted,
    }
