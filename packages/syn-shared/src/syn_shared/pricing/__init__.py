"""Centralized model pricing for token cost estimation.

Single source of truth for LLM model pricing across the platform.
All packages (syn-domain, syn-tokens, syn-adapters) import from here.

Cost is computed from THIS table, for every provider. A harness-reported cost
(the Claude CLI's ``total_cost_usd``) is a cross-check, not the source of
truth: Anthropic documents it as a client-side estimate from a price table
bundled at build time and states it must not drive financial decisions.
Codex reports no cost at all. See ADR-067 (D-1).

An unknown model must never be priced by substitution. Every resolver here
either returns a real rate or says so explicitly - see ``PricedAmount``.

To update pricing when a vendor ships or reprices a model:
1. Add/update entries in ``MODEL_PRICING_TABLE`` below
2. Run ``just qa`` to verify all consumers still pass

ADR-067 replaces step 1 with generation from the agentic-primitives model
registry; until that lands this table is hand-maintained and its rates were
verified 2026-08-16.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from syn_shared.agents import ModelAlias, ModelId

logger = logging.getLogger(__name__)

_MILLION = Decimal("1_000_000")


class UnknownModelPricingError(LookupError):
    """Raised when a caller requires a rate and no rate exists for the model."""


class PricingStatus(StrEnum):
    """Why a cost is, or is not, a real number.

    Exists so "we could not price this" can never be mistaken for "this was
    free". A bare ``Decimal("0")`` return is what let unpriced codex runs
    render as ``$0.00`` across the API, CLI and dashboard (ADR-067 D3).
    """

    PRICED = "priced"
    """Computed from a verified rate for a known model."""

    PLACEHOLDER = "placeholder"
    """Computed, but from an unconfirmed rate. Treat as an estimate."""

    UNPRICED_UNKNOWN_MODEL = "unpriced_unknown_model"
    """No model id was recorded, so no rate could be selected."""

    UNPRICED_NO_RATE = "unpriced_no_rate"
    """A model id was recorded but the table has no rate for it."""


@dataclass(frozen=True)
class PricedAmount:
    """A cost together with the reason it does or does not exist.

    The only type a cost calculator may return. ``cost`` is ``None`` for every
    non-priced status, which makes "unpriced" structurally impossible to
    confuse with zero at any downstream hop.
    """

    cost: Decimal | None
    status: PricingStatus
    model: str | None = None

    def __post_init__(self) -> None:
        """Reject states where ``cost`` contradicts ``status``.

        The ``unpriced()`` factory guarded one direction, but direct
        construction could still produce ``PricedAmount(None, PRICED)`` or
        ``PricedAmount(Decimal("1"), UNPRICED_NO_RATE)`` - a cost that lies
        about its own provenance, which is the failure this type exists to
        prevent. Validating here makes both unrepresentable.

        Note a priced cost of exactly ``0`` is legitimate: a known model that
        consumed zero tokens really did cost nothing. That is why the invariant
        keys on null-ness, not on truthiness.
        """
        priced = self.status in (PricingStatus.PRICED, PricingStatus.PLACEHOLDER)
        if priced and self.cost is None:
            msg = f"status {self.status} requires a cost, got None"
            raise ValueError(msg)
        if not priced and self.cost is not None:
            msg = f"status {self.status} must have cost=None, got {self.cost}"
            raise ValueError(msg)

    @property
    def is_priced(self) -> bool:
        """True when this amount carries a real (verified or placeholder) rate.

        Derived from ``status``, not from ``cost``, so a legitimate zero-token
        cost of ``0`` is still priced.
        """
        return self.status in (PricingStatus.PRICED, PricingStatus.PLACEHOLDER)

    @classmethod
    def unpriced(cls, status: PricingStatus, model: str | None = None) -> PricedAmount:
        """Build an unpriced amount, guarding against a priced status."""
        if status in (PricingStatus.PRICED, PricingStatus.PLACEHOLDER):
            msg = f"{status} is a priced status; use PricedAmount(cost=..., status=...)"
            raise ValueError(msg)
        return cls(cost=None, status=status, model=model)


# `gpt-5.6` is OpenAI's ALIAS for `gpt-5.6-sol`, not a distinct model, so it
# carries Sol's published rates.
#
# Source: https://developers.openai.com/api/docs/pricing (2026-08-26).
#
# THESE ARE THE SHORT-CONTEXT RATES. OpenAI bills gpt-5.6 in two context tiers.
# The multiplier is NOT uniform: input, cached input and cache write are 2x,
# output is 1.5x (Sol long: $8.00 in, $30.00 out). This table has no tier
# concept, so a run above the long-context threshold is UNDER-priced. Observed sessions on this platform run 897 to
# ~28k input tokens, comfortably short-tier, so short is the correct default.
# Tiering is tracked separately; see the issue linked from ADR-067 phase 2.
#
# WHY THIS KEEPS BEING WRONG. These values have been incorrect twice. They were
# an unverified $15/$60/$1.50 TODO(#780) placeholder, then "verified" on
# 2026-08-16 to $5/$30/$0.50 - which matches no gpt-5.6 tier at all, but IS an
# exact match for OpenAI's `chat-latest` ($5.00 in / $0.50 cached / $30.00 out)
# in the Specialized models table. The entry's own comment says Sol is "the
# model a ChatGPT-account codex login actually runs", so the likely mistake was
# pricing the ChatGPT model rather than the API model. The $6.25 cache write was
# invented; `chat-latest` publishes no cache-write rate.
#
# PROMOTIONAL. The vendor page states Sol's pricing is promotional "at least
# through November 21, 2026". These rates have a known expiry; recheck then.
#
# SERVICE TIERS. OpenAI publishes four (Standard, Batch, Flex, Fast mode). Sol
# short-context output spans $10.00 (Batch/Flex) to $40.00 (Fast). Standard is
# used here because codex does not set `service_tier`. This is also why the
# OpenRouter listing reads $2.00/$10.00: that is the Batch/Flex column, not a
# discount to chase.
#
# DO NOT "correct" these down to the OpenRouter models API. Its $2.00/$10.00
# listing for Sol is OpenAI's Batch/Flex column, not the Standard rate this
# platform bills at. Useful for relative sanity, misleading for absolute rates.
_GPT_5_6_CODEX_INPUT_PER_MILLION = Decimal("4.00")
_GPT_5_6_CODEX_OUTPUT_PER_MILLION = Decimal("20.00")
_GPT_5_6_CODEX_CACHED_INPUT_PER_MILLION = Decimal("0.40")
_GPT_5_6_CODEX_CACHE_WRITE_PER_MILLION = Decimal("5.00")


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
# Pricing table: all supported Claude models
#
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
# Last updated: 2026-04-06
#
# Cache pricing multipliers (relative to base input price):
#   - Cache creation (5-min TTL): 1.25x
#   - Cache read:                 0.10x
# ---------------------------------------------------------------------------

MODEL_PRICING_TABLE: dict[ModelId, ModelPricing] = {
    # --- Current generation (ADR-067 phase 0) ---
    # ANTHROPIC ROWS ONLY: verified 2026-08-16 against the vendor pricing pages
    # and cross-checked against the OpenRouter models API; both agreed. Cache
    # rates follow Anthropic's documented multipliers (read 0.10x, 5-min write
    # 1.25x of base input).
    #
    # The OpenAI rows are NOT covered by that cross-check and must not be read
    # as if they were. OpenRouter lists Sol at OpenAI's Batch/Flex price, not
    # Standard, so the two sources do not agree there. See the gpt-5.6 block
    # above for the authoritative source and its caveats.
    ModelId.CLAUDE_OPUS_5: ModelPricing(
        model_id=ModelId.CLAUDE_OPUS_5,
        input_per_million=Decimal("5.00"),
        output_per_million=Decimal("25.00"),
        cache_creation_per_million=Decimal("6.25"),
        cache_read_per_million=Decimal("0.50"),
    ),
    ModelId.CLAUDE_SONNET_5: ModelPricing(
        model_id=ModelId.CLAUDE_SONNET_5,
        input_per_million=Decimal("2.00"),
        output_per_million=Decimal("10.00"),
        cache_creation_per_million=Decimal("2.50"),
        cache_read_per_million=Decimal("0.20"),
    ),
    ModelId.CLAUDE_FABLE_5: ModelPricing(
        model_id=ModelId.CLAUDE_FABLE_5,
        input_per_million=Decimal("10.00"),
        output_per_million=Decimal("50.00"),
        cache_creation_per_million=Decimal("12.50"),
        cache_read_per_million=Decimal("1.00"),
    ),
    ModelId.CLAUDE_HAIKU_4_5: ModelPricing(
        model_id=ModelId.CLAUDE_HAIKU_4_5,
        input_per_million=Decimal("1.00"),
        output_per_million=Decimal("5.00"),
        cache_creation_per_million=Decimal("1.25"),
        cache_read_per_million=Decimal("0.10"),
    ),
    # The model a ChatGPT-account codex login actually runs. Distinct from the
    # legacy GPT_5_6 entry below, which codex rejects under that auth mode.
    ModelId.GPT_5_6_SOL: ModelPricing(
        model_id=ModelId.GPT_5_6_SOL,
        input_per_million=_GPT_5_6_CODEX_INPUT_PER_MILLION,
        output_per_million=_GPT_5_6_CODEX_OUTPUT_PER_MILLION,
        cache_creation_per_million=_GPT_5_6_CODEX_CACHE_WRITE_PER_MILLION,
        cache_read_per_million=_GPT_5_6_CODEX_CACHED_INPUT_PER_MILLION,
    ),
    # Short-context rates, same source and caveats as Sol above.
    ModelId.GPT_5_6_TERRA: ModelPricing(
        model_id=ModelId.GPT_5_6_TERRA,
        input_per_million=Decimal("2.00"),
        output_per_million=Decimal("12.00"),
        cache_creation_per_million=Decimal("2.50"),
        cache_read_per_million=Decimal("0.20"),
    ),
    ModelId.GPT_5_6_LUNA: ModelPricing(
        model_id=ModelId.GPT_5_6_LUNA,
        input_per_million=Decimal("0.20"),
        output_per_million=Decimal("1.20"),
        cache_creation_per_million=Decimal("0.25"),
        cache_read_per_million=Decimal("0.02"),
    ),
    # --- Previous generation (kept: historical sessions reference these) ---
    ModelId.CLAUDE_OPUS_4_5: ModelPricing(
        model_id=ModelId.CLAUDE_OPUS_4_5,
        input_per_million=Decimal("5.00"),
        output_per_million=Decimal("25.00"),
        cache_creation_per_million=Decimal("6.25"),
        cache_read_per_million=Decimal("0.50"),
    ),
    ModelId.CLAUDE_SONNET_4_5: ModelPricing(
        model_id=ModelId.CLAUDE_SONNET_4_5,
        input_per_million=Decimal("3.00"),
        output_per_million=Decimal("15.00"),
        cache_creation_per_million=Decimal("3.75"),
        cache_read_per_million=Decimal("0.30"),
    ),
    # --- OpenAI Codex family (legacy) ---
    ModelId.GPT_5_6: ModelPricing(
        model_id=ModelId.GPT_5_6,
        input_per_million=_GPT_5_6_CODEX_INPUT_PER_MILLION,
        output_per_million=_GPT_5_6_CODEX_OUTPUT_PER_MILLION,
        cache_creation_per_million=_GPT_5_6_CODEX_CACHE_WRITE_PER_MILLION,
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
        # Haiku 3.5 is $0.80/$4.00, NOT Haiku 4.5's $1.00/$5.00. The old row
        # carried 4.5's rates under 3.5's id (25% over) - found by cross-model
        # review of #816.
        input_per_million=Decimal("0.80"),
        output_per_million=Decimal("4.00"),
        cache_creation_per_million=Decimal("1.00"),
        cache_read_per_million=Decimal("0.08"),
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

# Models whose rates are not yet confirmed against the vendor's published
# pricing. A cost computed from these is real arithmetic on an unverified
# rate, so it is reported with PricingStatus.PLACEHOLDER rather than PRICED
# and must not be presented with the same confidence as a verified figure.
PLACEHOLDER_PRICED_MODELS: frozenset[ModelId] = frozenset()

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
#
# ADR-067 phase 0: these aliases pointed at superseded models (opus -> Opus 4,
# sonnet -> Sonnet 4, haiku -> Haiku 3.5) while the CLI resolved them to the
# current generation. Costs happened to survive because the CLI reports its
# own total, but every session was ATTRIBUTED to a model two generations old,
# and any fallback pricing used the wrong rate. Aliases must track whatever
# the harness currently resolves them to; when a new generation ships, this
# map moves with it.
MODEL_ALIASES: dict[str, ModelId] = {
    "gpt-codex": ModelId.GPT_5_6,
    ModelAlias.OPUS: ModelId.CLAUDE_OPUS_5,
    ModelAlias.SONNET: ModelId.CLAUDE_SONNET_5,
    ModelAlias.HAIKU: ModelId.CLAUDE_HAIKU_4_5,
    ModelAlias.FABLE: ModelId.CLAUDE_FABLE_5,
    # Undated family names the CLI also accepts. Only ids that DIFFER from a
    # ModelId value need an entry: canonical_model_id() already falls back to
    # ModelId(value), so the Claude 5 ids (which are undated) resolve on their
    # own. Listing them here would also trip the bare-model-literal poka-yoke.
    "claude-haiku-4-5": ModelId.CLAUDE_HAIKU_4_5,
    "claude-opus-4-5": ModelId.CLAUDE_OPUS_4_5,
    "claude-sonnet-4-5": ModelId.CLAUDE_SONNET_4_5,
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
    """Resolve pricing for a known model. Returns ``None`` when unknown.

    Exact resolution only: an alias, or an id present in the table. There is
    deliberately NO prefix matching.

    A prefix heuristic used to live here, mapping any id that started with a
    known family and ended in 8 digits onto that family's current rate - so a
    future snapshot like ``claude-sonnet-4-20991231`` silently priced at
    today's Sonnet 4 rate, with no signal that the price was inferred rather
    than looked up. Vendors reprice across snapshots (Opus 4 at $15/$75 versus
    Opus 4.5 at $5/$25), so guessing by family name is guessing at money
    (ADR-067 D4).
    """
    canonical = canonical_model_id(model_id)
    if canonical is not None:
        return MODEL_PRICING_TABLE[canonical]
    return None


def price_tokens(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
    *,
    context: str = "",
) -> PricedAmount:
    """Price token usage, or say why it could not be priced.

    This is the only cost entry point production code should use. It never
    substitutes a model and never returns a bare zero: an unknown or missing
    model yields an unpriced ``PricedAmount`` and a WARNING naming the model,
    so unpriced runs are greppable rather than silently rendered as ``$0.00``.

    Args:
        model: Recorded model id or alias. ``None`` when the harness reported
            no model (codex does not report one on the wire).
        context: Optional identifier (session id, execution id) for the log
            line, so an unpriced run can be traced back to its source.
    """
    if not model:
        logger.warning(
            "unpriced token usage: no model recorded (in=%d out=%d cache_creation=%d cache_read=%d) %s",
            input_tokens,
            output_tokens,
            cache_creation,
            cache_read,
            context,
        )
        return PricedAmount.unpriced(PricingStatus.UNPRICED_UNKNOWN_MODEL)

    pricing = resolve_model_pricing(model)
    if pricing is None:
        logger.warning(
            "unpriced token usage: no rate for model %r (in=%d out=%d cache_creation=%d cache_read=%d) %s",
            model,
            input_tokens,
            output_tokens,
            cache_creation,
            cache_read,
            context,
        )
        return PricedAmount.unpriced(PricingStatus.UNPRICED_NO_RATE, model=model)

    cost = pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)
    status = (
        PricingStatus.PLACEHOLDER
        if pricing.model_id in PLACEHOLDER_PRICED_MODELS
        else PricingStatus.PRICED
    )
    return PricedAmount(cost=cost, status=status, model=str(pricing.model_id))


def require_model_pricing(model_id: str) -> ModelPricing:
    """Resolve pricing or raise. Use when a caller cannot proceed unpriced.

    Replaces the former ``get_model_pricing``, which fell back to Sonnet 4 for
    any unknown model - including the empty string - and so priced unknown
    models confidently and wrongly (ADR-067 D4).
    """
    pricing = resolve_model_pricing(model_id)
    if pricing is None:
        msg = (
            f"No pricing for model {model_id!r}. Add it to MODEL_PRICING_TABLE "
            f"rather than pricing it as a different model."
        )
        raise UnknownModelPricingError(msg)
    return pricing


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> Decimal:
    """Calculate cost for token usage, raising when the model has no rate.

    ``model`` is REQUIRED. It previously defaulted to Sonnet 4, which meant a
    caller that forgot to pass one silently billed at Sonnet rates; the same
    default made unknown models resolve to a confident, wrong number
    (ADR-067 D4).

    Prefer :func:`price_tokens` in production paths - it reports "unpriced"
    instead of raising, which is usually what an observability pipeline wants.
    Use this when a caller genuinely cannot proceed without a rate.

    Raises:
        UnknownModelPricingError: If no rate exists for ``model``.
    """
    pricing = require_model_pricing(model)
    return pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)


__all__ = [
    "MODEL_ALIASES",
    "MODEL_PRICING_TABLE",
    "PLACEHOLDER_PRICED_MODELS",
    "ModelPricing",
    "PricedAmount",
    "PricingStatus",
    "UnknownModelPricingError",
    "calculate_cost",
    "price_tokens",
    "require_model_pricing",
    "resolve_model_pricing",
]
