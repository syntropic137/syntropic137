"""ScreeningPort adapters for the feedback context (ADR-076-feedback-ticketing).

``HeuristicScreener`` needs no model and is the self-host default and the
floor every model candidate is benchmarked against. ``AnthropicScreener``
asks one explicit Claude model through a closed output schema. Which one runs
is decided by the bench (``scripts/feedback_screening_bench.py``), never here.
"""

from syn_adapters.feedback_screening.anthropic import (
    AnthropicModelId,
    AnthropicScreener,
    ScreeningUnavailableError,
    parse_screening_reply,
)
from syn_adapters.feedback_screening.heuristic import HeuristicScreener

__all__ = [
    "AnthropicModelId",
    "AnthropicScreener",
    "HeuristicScreener",
    "ScreeningUnavailableError",
    "parse_screening_reply",
]
