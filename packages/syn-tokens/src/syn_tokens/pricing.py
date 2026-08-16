"""Claude model pricing and cost calculation.

Re-exports from ``syn_shared.pricing`` — the single source of truth
for model pricing across the platform.

Backward-compatible: ``CLAUDE_PRICING``, ``DEFAULT_MODEL``, and
``calculate_cost()`` are preserved for existing importers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

from syn_shared.agents import ModelId
from syn_shared.pricing import (
    MODEL_PRICING_TABLE,
    ModelPricing,
    calculate_cost,
    price_tokens,
    require_model_pricing,
)

# Baseline model used for PRE-DISPATCH budget estimation only.
#
# This is not a default model and must never be used to price actual usage.
# `SpendTracker.check_budget` runs before a phase starts, when the model that
# will run is not yet known to the caller (the budget-checker protocol does not
# carry one), so it needs *some* rate to turn a token estimate into a dollar
# estimate. Naming it explicitly keeps it from masquerading as "the model's
# price" the way the old `DEFAULT_MODEL` did (ADR-067 D4).
#
# TODO(#780): thread the phase's real model through the budget-checker protocol
# so pre-dispatch estimates use the rate that will actually apply.
BUDGET_ESTIMATION_MODEL: str = ModelId.CLAUDE_SONNET_5

# Backward-compatible dict for code that reads CLAUDE_PRICING directly
CLAUDE_PRICING: dict[str, dict[str, Decimal]] = {
    model_id: {
        "input": p.input_per_million,
        "output": p.output_per_million,
    }
    for model_id, p in MODEL_PRICING_TABLE.items()
}

__all__ = [
    "BUDGET_ESTIMATION_MODEL",
    "CLAUDE_PRICING",
    "MODEL_PRICING_TABLE",
    "ModelPricing",
    "calculate_cost",
    "price_tokens",
    "require_model_pricing",
]
