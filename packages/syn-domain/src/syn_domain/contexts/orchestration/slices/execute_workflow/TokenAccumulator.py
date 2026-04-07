"""Token accumulation state machine for workflow execution.

Extracted from WorkflowExecutionEngine to isolate token tracking
and cost estimation concerns.
"""

from __future__ import annotations

from decimal import Decimal

from syn_shared.pricing import DEFAULT_MODEL_ID, get_model_pricing


class TokenAccumulator:
    """Accumulates token usage across streaming events and estimates cost.

    Uses ``syn_shared.pricing`` for model-aware cost estimation including
    cache token pricing.
    """

    def __init__(self, model: str = DEFAULT_MODEL_ID) -> None:
        self._model = model
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._cache_creation_tokens: int = 0
        self._cache_read_tokens: int = 0

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Record token usage from a streaming event."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._cache_creation_tokens += cache_creation_tokens
        self._cache_read_tokens += cache_read_tokens

    def estimate_cost(self) -> Decimal:
        """Estimate cost based on accumulated token usage."""
        pricing = get_model_pricing(self._model)
        return pricing.calculate_cost(
            self._input_tokens,
            self._output_tokens,
            self._cache_creation_tokens,
            self._cache_read_tokens,
        )

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    @property
    def output_tokens(self) -> int:
        return self._output_tokens

    @property
    def cache_creation_tokens(self) -> int:
        return self._cache_creation_tokens

    @property
    def cache_read_tokens(self) -> int:
        return self._cache_read_tokens

    @property
    def total_tokens(self) -> int:
        return self._input_tokens + self._output_tokens
