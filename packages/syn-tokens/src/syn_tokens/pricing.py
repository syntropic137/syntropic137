"""Claude model pricing and cost calculation.

Extracted from spend.py to reduce module complexity.
"""

from __future__ import annotations

from decimal import Decimal

# Claude pricing (per 1M tokens)
CLAUDE_PRICING = {
    "claude-3-5-sonnet-20241022": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-3-opus-20240229": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
    },
    "claude-3-haiku-20240307": {
        "input": Decimal("0.25"),
        "output": Decimal("1.25"),
    },
}

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = DEFAULT_MODEL,
) -> Decimal:
    """Calculate cost for token usage.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Claude model name

    Returns:
        Cost in USD
    """
    pricing = CLAUDE_PRICING.get(model, CLAUDE_PRICING[DEFAULT_MODEL])

    input_cost = Decimal(input_tokens) * pricing["input"] / Decimal("1000000")
    output_cost = Decimal(output_tokens) * pricing["output"] / Decimal("1000000")

    return input_cost + output_cost
