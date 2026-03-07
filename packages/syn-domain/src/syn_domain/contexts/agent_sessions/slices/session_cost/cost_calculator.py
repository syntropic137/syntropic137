"""Cost calculator for session token usage."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelPricing:
    """Pricing per 1M tokens for a model."""

    input_per_million: Decimal
    output_per_million: Decimal
    cache_write_per_million: Decimal
    cache_read_per_million: Decimal


DEFAULT_PRICING = ModelPricing(
    input_per_million=Decimal("3.00"),
    output_per_million=Decimal("15.00"),
    cache_write_per_million=Decimal("3.75"),
    cache_read_per_million=Decimal("0.30"),
)


class CostCalculator:
    """Calculates token costs using configurable pricing."""

    def __init__(self, pricing: ModelPricing | None = None) -> None:
        self._pricing = pricing or DEFAULT_PRICING

    def calculate_token_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
        model: str | None = None,  # noqa: ARG002 — reserved for future per-model pricing
    ) -> Decimal:
        """Calculate cost from token counts.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_creation: Cache write tokens
            cache_read: Cache read tokens
            model: Model name (reserved for per-model pricing)

        Returns:
            Total cost in USD
        """
        p = self._pricing
        input_cost = (Decimal(input_tokens) / 1_000_000) * p.input_per_million
        output_cost = (Decimal(output_tokens) / 1_000_000) * p.output_per_million
        cache_write_cost = (Decimal(cache_creation) / 1_000_000) * p.cache_write_per_million
        cache_read_cost = (Decimal(cache_read) / 1_000_000) * p.cache_read_per_million
        return input_cost + output_cost + cache_write_cost + cache_read_cost
