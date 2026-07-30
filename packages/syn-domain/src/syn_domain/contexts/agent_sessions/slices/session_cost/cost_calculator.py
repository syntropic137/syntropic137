"""Cost calculator for session token usage.

Delegates pricing to ``syn_shared.pricing`` — the single source of truth
for model pricing across the platform.
"""

from decimal import Decimal

from syn_shared.pricing import ModelPricing, resolve_model_pricing


class CostCalculator:
    """Calculates token costs using model-specific pricing.

    Uses the STRICT resolver (``resolve_model_pricing``), never the
    legacy-fallback ``get_model_pricing``. An unknown or missing model
    MUST NOT be priced as any real model - a codex phase with no
    ``model:`` was previously priced as Claude Haiku, then Claude Sonnet
    after a partial fix, because callers fell back through
    ``get_model_pricing(model or "")`` (issue #788). This calculator
    contributes zero cost instead of guessing.
    """

    def resolve_pricing(self, model: str | None) -> ModelPricing | None:
        """Resolve pricing for a model, or ``None`` if unknown/missing.

        Args:
            model: Model name, or ``None``/empty when the model is unknown.

        Returns:
            ``ModelPricing`` for a recognized model, ``None`` otherwise.
        """
        if not model:
            return None
        return resolve_model_pricing(model)

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
            Total cost in USD. ``Decimal("0")`` when the model is unknown
            or missing - never a guessed price from a default model.
        """
        pricing = self.resolve_pricing(model)
        if pricing is None:
            return Decimal("0")
        return pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)
