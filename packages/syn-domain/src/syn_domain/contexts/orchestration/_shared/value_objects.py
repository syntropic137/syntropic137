"""Value objects for costs domain."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


_MILLION = Decimal("1000000")


def _token_cost(count: int, price_per_million: Decimal | None) -> Decimal:
    """Calculate cost for a token count at a given price per million."""
    if not price_per_million or not count:
        return Decimal("0")
    return (Decimal(count) * price_per_million) / _MILLION


class CostType(str, Enum):
    """Types of costs that can be incurred."""

    LLM_TOKENS = "llm_tokens"
    TOOL_EXECUTION = "tool_execution"
    COMPUTE = "compute"


@dataclass(frozen=True)
class CostAmount:
    """Represents a monetary cost amount in USD.

    Uses Decimal for precise financial calculations.
    """

    value: Decimal

    def __post_init__(self) -> None:
        """Validate the cost amount."""
        if self.value < 0:
            raise ValueError("Cost amount cannot be negative")

    @classmethod
    def zero(cls) -> "CostAmount":
        """Create a zero cost amount."""
        return cls(Decimal("0"))

    @classmethod
    def from_float(cls, value: float) -> "CostAmount":
        """Create from a float value."""
        return cls(Decimal(str(value)))

    def __add__(self, other: "CostAmount") -> "CostAmount":
        """Add two cost amounts."""
        return CostAmount(self.value + other.value)

    def __str__(self) -> str:
        """Format as USD string with adaptive precision."""
        return self.format_usd()

    def format_usd(self) -> str:
        """Format as USD string with adaptive precision.

        Precision rules:
        - >= $1.00: 2 decimal places (e.g., $1.52)
        - >= $0.01: 4 decimal places (e.g., $0.0523)
        - < $0.01: 6 decimal places (e.g., $0.000234)
        """
        if self.value >= Decimal("1.00"):
            return f"${self.value:.2f}"
        elif self.value >= Decimal("0.01"):
            return f"${self.value:.4f}"
        else:
            return f"${self.value:.6f}"


@dataclass(frozen=True)
class TokenCount:
    """Represents token counts for LLM usage."""

    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    def __post_init__(self) -> None:
        """Validate token counts."""
        if self.input_tokens < 0:
            raise ValueError("Input tokens cannot be negative")
        if self.output_tokens < 0:
            raise ValueError("Output tokens cannot be negative")
        if self.cache_creation_tokens < 0:
            raise ValueError("Cache creation tokens cannot be negative")
        if self.cache_read_tokens < 0:
            raise ValueError("Cache read tokens cannot be negative")

    @property
    def total(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

    @classmethod
    def zero(cls) -> "TokenCount":
        """Create a zero token count."""
        return cls(0, 0, 0, 0)

    def __add__(self, other: "TokenCount") -> "TokenCount":
        """Add two token counts."""
        return TokenCount(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass(frozen=True)
class ModelPricing:
    """Pricing information for an LLM model.

    Prices are in USD per million tokens.
    """

    model_id: str
    input_price_per_million: Decimal
    output_price_per_million: Decimal
    cache_creation_price_per_million: Decimal | None = None
    cache_read_price_per_million: Decimal | None = None

    def calculate_cost(self, tokens: TokenCount) -> CostAmount:
        """Calculate the cost for given token counts."""
        input_cost = _token_cost(tokens.input_tokens, self.input_price_per_million)
        output_cost = _token_cost(tokens.output_tokens, self.output_price_per_million)
        cache_creation_cost = _token_cost(
            tokens.cache_creation_tokens, self.cache_creation_price_per_million,
        )
        cache_read_cost = _token_cost(
            tokens.cache_read_tokens, self.cache_read_price_per_million,
        )
        return CostAmount(input_cost + output_cost + cache_creation_cost + cache_read_cost)


# Default pricing for common models (prices in USD per million tokens)
DEFAULT_MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-20250514": ModelPricing(
        model_id="claude-sonnet-4-20250514",
        input_price_per_million=Decimal("3.00"),
        output_price_per_million=Decimal("15.00"),
        cache_creation_price_per_million=Decimal("3.75"),
        cache_read_price_per_million=Decimal("0.30"),
    ),
    "claude-3-5-sonnet-20241022": ModelPricing(
        model_id="claude-3-5-sonnet-20241022",
        input_price_per_million=Decimal("3.00"),
        output_price_per_million=Decimal("15.00"),
        cache_creation_price_per_million=Decimal("3.75"),
        cache_read_price_per_million=Decimal("0.30"),
    ),
    "claude-3-opus-20240229": ModelPricing(
        model_id="claude-3-opus-20240229",
        input_price_per_million=Decimal("15.00"),
        output_price_per_million=Decimal("75.00"),
        cache_creation_price_per_million=Decimal("18.75"),
        cache_read_price_per_million=Decimal("1.50"),
    ),
    "claude-3-haiku-20240307": ModelPricing(
        model_id="claude-3-haiku-20240307",
        input_price_per_million=Decimal("0.25"),
        output_price_per_million=Decimal("1.25"),
        cache_creation_price_per_million=Decimal("0.30"),
        cache_read_price_per_million=Decimal("0.03"),
    ),
}


def get_model_pricing(model_id: str) -> ModelPricing:
    """Get pricing for a model, with fallback to Sonnet pricing.

    Args:
        model_id: The model identifier.

    Returns:
        ModelPricing for the model.
    """
    if model_id in DEFAULT_MODEL_PRICING:
        return DEFAULT_MODEL_PRICING[model_id]

    # Fallback: try to match by prefix
    for key, pricing in DEFAULT_MODEL_PRICING.items():
        if model_id.startswith(key.rsplit("-", 1)[0]):
            return pricing

    # Default to Sonnet pricing
    return DEFAULT_MODEL_PRICING["claude-sonnet-4-20250514"]
