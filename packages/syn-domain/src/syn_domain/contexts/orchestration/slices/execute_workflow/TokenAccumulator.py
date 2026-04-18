"""Token accumulation state machine for workflow execution.

Extracted from WorkflowExecutionEngine to isolate token tracking concerns.
Cost is Lane 2 telemetry and is computed from authoritative Claude CLI
totals downstream (see session_cost / execution_cost projections).
"""

from __future__ import annotations


class TokenAccumulator:
    """Accumulates token usage across streaming events."""

    def __init__(self) -> None:
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
        return (
            self._input_tokens
            + self._output_tokens
            + self._cache_creation_tokens
            + self._cache_read_tokens
        )
