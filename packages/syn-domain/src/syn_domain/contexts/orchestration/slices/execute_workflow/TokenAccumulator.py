"""Token accumulation state machine for workflow execution.

Extracted from WorkflowExecutionEngine to isolate token tracking
and cost estimation concerns.
"""

from __future__ import annotations

from decimal import Decimal


class TokenAccumulator:
    """Accumulates token usage across streaming events and estimates cost.

    Pure state machine with no external dependencies.
    """

    # Claude Sonnet 4 pricing (per million tokens)
    _INPUT_PRICE = Decimal("3.00") / Decimal("1000000")
    _OUTPUT_PRICE = Decimal("15.00") / Decimal("1000000")

    def __init__(self) -> None:
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def record(self, input_tokens: int, output_tokens: int) -> None:
        """Record token usage from a streaming event."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def estimate_cost(self) -> Decimal:
        """Estimate cost based on accumulated token usage."""
        return (
            Decimal(self._input_tokens) * self._INPUT_PRICE
            + Decimal(self._output_tokens) * self._OUTPUT_PRICE
        )

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    @property
    def output_tokens(self) -> int:
        return self._output_tokens

    @property
    def total_tokens(self) -> int:
        return self._input_tokens + self._output_tokens
