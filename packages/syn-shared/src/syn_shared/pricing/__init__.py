"""Centralized model pricing for token cost estimation.

Single source of truth for LLM model pricing across the platform.
All packages (syn-domain, syn-tokens, syn-adapters) import from here.

Note: These prices are used for real-time cost *estimates* during execution.
The authoritative final cost comes from the Claude SDK's ``total_cost_usd``
in the session result event, which overwrites accumulated estimates.

To update pricing when Anthropic releases new models or changes rates:
1. Add/update entries in ``MODEL_PRICING_TABLE`` below
2. Run ``just qa`` to verify all consumers still pass
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from syn_shared.agents import ModelAlias, ModelId

_MILLION = Decimal("1_000_000")

# TODO(#780): confirm GPT-5.6 codex rate (placeholder estimate until confirmed)
_GPT_5_6_CODEX_INPUT_PER_MILLION = Decimal("15.0")
# TODO(#780): confirm GPT-5.6 codex rate (placeholder estimate until confirmed)
_GPT_5_6_CODEX_OUTPUT_PER_MILLION = Decimal("60.0")
# TODO(#780): confirm GPT-5.6 codex rate (placeholder estimate until confirmed)
_GPT_5_6_CODEX_CACHED_INPUT_PER_MILLION = Decimal("1.5")


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for an LLM model, in USD per million tokens."""

    model_id: ModelId
    input_per_million: Decimal
    output_per_million: Decimal
    cache_creation_per_million: Decimal
    cache_read_per_million: Decimal

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
    ) -> Decimal:
        """Calculate cost from token counts.

        Returns:
            Total cost in USD.
        """
        return (
            Decimal(input_tokens) * self.input_per_million / _MILLION
            + Decimal(output_tokens) * self.output_per_million / _MILLION
            + Decimal(cache_creation) * self.cache_creation_per_million / _MILLION
            + Decimal(cache_read) * self.cache_read_per_million / _MILLION
        )


# ---------------------------------------------------------------------------
# Pricing table — all supported Claude models
#
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
# Last updated: 2026-04-06
#
# Cache pricing multipliers (relative to base input price):
#   - Cache creation (5-min TTL): 1.25x
#   - Cache read:                 0.10x
# ---------------------------------------------------------------------------

MODEL_PRICING_TABLE: dict[ModelId, ModelPricing] = {
    # --- OpenAI Codex family ---
    ModelId.GPT_5_6: ModelPricing(
        model_id=ModelId.GPT_5_6,
        input_per_million=_GPT_5_6_CODEX_INPUT_PER_MILLION,
        output_per_million=_GPT_5_6_CODEX_OUTPUT_PER_MILLION,
        cache_creation_per_million=_GPT_5_6_CODEX_INPUT_PER_MILLION,
        cache_read_per_million=_GPT_5_6_CODEX_CACHED_INPUT_PER_MILLION,
    ),
    # --- Claude 4.x family ---
    ModelId.CLAUDE_OPUS_4: ModelPricing(
        model_id=ModelId.CLAUDE_OPUS_4,
        input_per_million=Decimal("15.00"),
        output_per_million=Decimal("75.00"),
        cache_creation_per_million=Decimal("18.75"),
        cache_read_per_million=Decimal("1.50"),
    ),
    ModelId.CLAUDE_SONNET_4: ModelPricing(
        model_id=ModelId.CLAUDE_SONNET_4,
        input_per_million=Decimal("3.00"),
        output_per_million=Decimal("15.00"),
        cache_creation_per_million=Decimal("3.75"),
        cache_read_per_million=Decimal("0.30"),
    ),
    # --- Claude 3.5 family ---
    ModelId.CLAUDE_SONNET_3_5: ModelPricing(
        model_id=ModelId.CLAUDE_SONNET_3_5,
        input_per_million=Decimal("3.00"),
        output_per_million=Decimal("15.00"),
        cache_creation_per_million=Decimal("3.75"),
        cache_read_per_million=Decimal("0.30"),
    ),
    ModelId.CLAUDE_HAIKU_3_5: ModelPricing(
        model_id=ModelId.CLAUDE_HAIKU_3_5,
        input_per_million=Decimal("1.00"),
        output_per_million=Decimal("5.00"),
        cache_creation_per_million=Decimal("1.25"),
        cache_read_per_million=Decimal("0.10"),
    ),
    # --- Claude 3 family (legacy) ---
    ModelId.CLAUDE_OPUS_3: ModelPricing(
        model_id=ModelId.CLAUDE_OPUS_3,
        input_per_million=Decimal("15.00"),
        output_per_million=Decimal("75.00"),
        cache_creation_per_million=Decimal("18.75"),
        cache_read_per_million=Decimal("1.50"),
    ),
    ModelId.CLAUDE_HAIKU_3: ModelPricing(
        model_id=ModelId.CLAUDE_HAIKU_3,
        input_per_million=Decimal("0.25"),
        output_per_million=Decimal("1.25"),
        cache_creation_per_million=Decimal("0.30"),
        cache_read_per_million=Decimal("0.03"),
    ),
}

# Default model for cost estimation when model is unknown
DEFAULT_MODEL_ID: ModelId = ModelId.CLAUDE_SONNET_4

# CLI alias → canonical model ID.
# The workflow YAML and AgentConfiguration use short names like
# ``sonnet``/``opus``/``haiku``; resolve them so pricing lookups don't
# silently fall back to the default.
#
# NOTE: no "codex" -> "gpt-5.6" alias. "codex" is a provider name
# (AgentProvider.CODEX), not a model id, and an earlier fix briefly used it
# as both at once - synthesizing "codex" as the model for a codex phase
# with no explicit `model:`. That collapsed "provider" and "model unknown"
# into the same string, which then silently priced unspecified-model codex
# phases as GPT-5.6 (issue #788 follow-up). A truly unknown model must
# resolve to no pricing, not a guessed one - see
# syn_shared.agents.DEFAULT_CLAUDE_MODEL.
MODEL_ALIASES: dict[str, ModelId] = {
    "gpt-codex": ModelId.GPT_5_6,
    ModelAlias.OPUS: ModelId.CLAUDE_OPUS_4,
    ModelAlias.SONNET: ModelId.CLAUDE_SONNET_4,
    ModelAlias.HAIKU: ModelId.CLAUDE_HAIKU_3_5,
    # Undated family names the CLI also accepts.
    "claude-sonnet-4": ModelId.CLAUDE_SONNET_4,
    "claude-opus-4": ModelId.CLAUDE_OPUS_4,
}


def canonical_model_id(model_id: str) -> ModelId | None:
    """Map an alias or raw identifier onto a known ``ModelId``, else ``None``.

    Returning ``None`` rather than echoing the input keeps "unknown model"
    a distinct, typed outcome instead of a plausible-looking string that
    later reads as a real id (issue #788).
    """
    aliased = MODEL_ALIASES.get(model_id)
    if aliased is not None:
        return aliased
    try:
        return ModelId(model_id)
    except ValueError:
        return None


def resolve_model_pricing(model_id: str) -> ModelPricing | None:
    """Resolve pricing for a known model without a default fallback."""
    canonical = canonical_model_id(model_id)
    if canonical is not None:
        return MODEL_PRICING_TABLE[canonical]

    for key, pricing in MODEL_PRICING_TABLE.items():
        family, separator, suffix = key.rpartition("-")
        if separator and suffix.isdigit() and len(suffix) == 8 and model_id.startswith(family):
            return pricing

    return None


def get_model_pricing(model_id: str) -> ModelPricing:
    """Get pricing for a model, with alias and prefix-match fallback.

    Resolution order:
    1. CLI alias (``sonnet``, ``opus``, ``haiku``) → canonical ID
    2. Exact match on model_id
    3. Prefix match (e.g., ``claude-sonnet-4-`` matches ``claude-sonnet-4-20250514``)
    4. Default to Sonnet 4 pricing

    Args:
        model_id: The model identifier (e.g., ``claude-sonnet-4-20250514``).

    Returns:
        ModelPricing for the model.
    """
    return resolve_model_pricing(model_id) or MODEL_PRICING_TABLE[DEFAULT_MODEL_ID]


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = DEFAULT_MODEL_ID,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> Decimal:
    """Calculate cost for token usage using model-specific pricing.

    Convenience function wrapping ``get_model_pricing().calculate_cost()``.

    Args:
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        model: Claude model name.
        cache_creation: Cache write tokens (1.25x input rate).
        cache_read: Cache read tokens (0.1x input rate).

    Returns:
        Cost in USD.
    """
    pricing = get_model_pricing(model)
    return pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)


__all__ = [
    "MODEL_ALIASES",
    "MODEL_PRICING_TABLE",
    "ModelPricing",
    "calculate_cost",
    "get_model_pricing",
    "resolve_model_pricing",
]
