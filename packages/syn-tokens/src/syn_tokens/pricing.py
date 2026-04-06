"""Claude model pricing and cost calculation.

Re-exports from ``syn_shared.pricing`` — the single source of truth
for model pricing across the platform.

Backward-compatible: ``CLAUDE_PRICING``, ``DEFAULT_MODEL``, and
``calculate_cost()`` are preserved for existing importers.
"""

from __future__ import annotations

from decimal import Decimal

from syn_shared.pricing import (
    MODEL_PRICING_TABLE,
    ModelPricing,
    calculate_cost,
    get_model_pricing,
)

# Backward-compatible aliases
DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Backward-compatible dict for code that reads CLAUDE_PRICING directly
CLAUDE_PRICING: dict[str, dict[str, Decimal]] = {
    model_id: {
        "input": p.input_per_million,
        "output": p.output_per_million,
    }
    for model_id, p in MODEL_PRICING_TABLE.items()
}

__all__ = [
    "CLAUDE_PRICING",
    "DEFAULT_MODEL",
    "MODEL_PRICING_TABLE",
    "ModelPricing",
    "calculate_cost",
    "get_model_pricing",
]
