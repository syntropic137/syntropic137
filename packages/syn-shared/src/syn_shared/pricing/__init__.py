"""Centralized model pricing for token cost estimation.

Single source of truth for LLM model pricing across the platform.
All packages (syn-domain, syn-tokens, syn-adapters) import from here.

Note: These prices are used for real-time cost *estimates* during execution.
The authoritative final cost comes from the Claude SDK's ``total_cost_usd``
in the session result event, which overwrites accumulated estimates.

To update pricing when Anthropic releases new models or changes rates:
1. Add/update entries in ``MODEL_PRICING_TABLE`` below
2. Run ``just qa`` to verify all consumers still pass
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_MILLION = Decimal("1_000_000")


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for an LLM model, in USD per million tokens."""

    model_id: str
    input_per_million: Decimal
    output_per_million: Decimal
    cache_creation_per_million: Decimal
    cache_read_per_million: Decimal

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
    ) -> Decimal:
        """Calculate cost from token counts.

        Returns:
            Total cost in USD.
        """
        return (
            Decimal(input_tokens) * self.input_per_million / _MILLION
            + Decimal(output_tokens) * self.output_per_million / _MILLION
            + Decimal(cache_creation) * self.cache_creation_per_million / _MILLION
            + Decimal(cache_read) * self.cache_read_per_million / _MILLION
        )


# ---------------------------------------------------------------------------
# Pricing table — all supported Claude models
#
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
# Last updated: 2026-04-06
#
# Cache pricing multipliers (relative to base input price):
#   - Cache creation (5-min TTL): 1.25x
#   - Cache read:                 0.10x
# ---------------------------------------------------------------------------

MODEL_PRICING_TABLE: dict[str, ModelPricing] = {
    # --- Claude 4.x family ---
    "claude-opus-4-20250514": ModelPricing(
        model_id="claude-opus-4-20250514",
        input_per_million=Decimal("15.00"),
        output_per_million=Decimal("75.00"),
        cache_creation_per_million=Decimal("18.75"),
        cache_read_per_million=Decimal("1.50"),
    ),
    "claude-sonnet-4-20250514": ModelPricing(
        model_id="claude-sonnet-4-20250514",
        input_per_million=Decimal("3.00"),
        output_per_million=Decimal("15.00"),
        cache_creation_per_million=Decimal("3.75"),
        cache_read_per_million=Decimal("0.30"),
    ),
    # --- Claude 3.5 family ---
    "claude-3-5-sonnet-20241022": ModelPricing(
        model_id="claude-3-5-sonnet-20241022",
        input_per_million=Decimal("3.00"),
        output_per_million=Decimal("15.00"),
        cache_creation_per_million=Decimal("3.75"),
        cache_read_per_million=Decimal("0.30"),
    ),
    "claude-3-5-haiku-20241022": ModelPricing(
        model_id="claude-3-5-haiku-20241022",
        input_per_million=Decimal("1.00"),
        output_per_million=Decimal("5.00"),
        cache_creation_per_million=Decimal("1.25"),
        cache_read_per_million=Decimal("0.10"),
    ),
    # --- Claude 3 family (legacy) ---
    "claude-3-opus-20240229": ModelPricing(
        model_id="claude-3-opus-20240229",
        input_per_million=Decimal("15.00"),
        output_per_million=Decimal("75.00"),
        cache_creation_per_million=Decimal("18.75"),
        cache_read_per_million=Decimal("1.50"),
    ),
    "claude-3-haiku-20240307": ModelPricing(
        model_id="claude-3-haiku-20240307",
        input_per_million=Decimal("0.25"),
        output_per_million=Decimal("1.25"),
        cache_creation_per_million=Decimal("0.30"),
        cache_read_per_million=Decimal("0.03"),
    ),
}

# Default model for cost estimation when model is unknown
DEFAULT_MODEL_ID = "claude-sonnet-4-20250514"


def get_model_pricing(model_id: str) -> ModelPricing:
    """Get pricing for a model, with prefix-match fallback.

    Resolution order:
    1. Exact match on model_id
    2. Prefix match (e.g., ``claude-sonnet-4-`` matches ``claude-sonnet-4-20250514``)
    3. Default to Sonnet 4 pricing

    Args:
        model_id: The model identifier (e.g., ``claude-sonnet-4-20250514``).

    Returns:
        ModelPricing for the model.
    """
    if model_id in MODEL_PRICING_TABLE:
        return MODEL_PRICING_TABLE[model_id]

    # Prefix fallback: strip the date suffix and try to match
    for key, pricing in MODEL_PRICING_TABLE.items():
        if model_id.startswith(key.rsplit("-", 1)[0]):
            return pricing

    return MODEL_PRICING_TABLE[DEFAULT_MODEL_ID]


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = DEFAULT_MODEL_ID,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> Decimal:
    """Calculate cost for token usage using model-specific pricing.

    Convenience function wrapping ``get_model_pricing().calculate_cost()``.

    Args:
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        model: Claude model name.
        cache_creation: Cache write tokens (1.25x input rate).
        cache_read: Cache read tokens (0.1x input rate).

    Returns:
        Cost in USD.
    """
    pricing = get_model_pricing(model)
    return pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)


__all__ = [
    "MODEL_PRICING_TABLE",
    "ModelPricing",
    "calculate_cost",
    "get_model_pricing",
]
