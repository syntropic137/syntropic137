"""Cost calculator for session token usage.

Delegates pricing to ``syn_shared.pricing`` — the single source of truth
for model pricing across the platform.
"""

from syn_shared.pricing import ModelPricing, PricedAmount, price_tokens, resolve_model_pricing


class CostCalculator:
    """Calculates token costs using model-specific pricing.

    Uses the STRICT resolver (``resolve_model_pricing``), never the
    legacy-fallback ``get_model_pricing``. An unknown or missing model
    MUST NOT be priced as any real model - a codex phase with no
    ``model:`` was previously priced as Claude Haiku, then Claude Sonnet
    after a partial fix, because callers fell back through
    ``get_model_pricing(model or "")`` (issue #788). This calculator
    reports that it could not price the work instead of guessing.
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
        *,
        context: str = "",
    ) -> PricedAmount:
        """Calculate cost from token counts, or say why it could not be.

        Returns a ``PricedAmount``, never a bare ``Decimal``. The old bare
        return had exactly one way to express "unknown model": ``Decimal("0")``
        - indistinguishable from a real zero, so every caller downstream
        rendered unpriced work as ``$0.00`` (issue #890). ``PricedAmount``
        carries ``cost=None`` for every unpriced status, which makes that
        conflation unrepresentable rather than merely discouraged.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_creation: Cache write tokens
            cache_read: Cache read tokens
            model: Model name for model-specific pricing
            context: Optional session/execution id, logged when unpriced so
                the run can be traced back to its source.

        Returns:
            A priced amount when the model is known, otherwise an unpriced
            one carrying the reason - never a guessed price from a default
            model, and never a zero standing in for "unknown".
        """
        return price_tokens(
            model,
            input_tokens,
            output_tokens,
            cache_creation,
            cache_read,
            context=context,
        )
