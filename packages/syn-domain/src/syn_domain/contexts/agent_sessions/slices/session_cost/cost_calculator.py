"""Cost calculator for session token usage.

Delegates pricing to ``syn_shared.pricing`` — the single source of truth
for model pricing across the platform.
"""

from decimal import Decimal

from syn_shared.pricing import get_model_pricing


class CostCalculator:
    """Calculates token costs using model-specific pricing."""

    def calculate_token_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
        model: str | None = None,
    ) -> Decimal:
        """Calculate cost from token counts.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_creation: Cache write tokens
            cache_read: Cache read tokens
            model: Model name for model-specific pricing

        Returns:
            Total cost in USD
        """
        pricing = get_model_pricing(model or "")
        return pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)
