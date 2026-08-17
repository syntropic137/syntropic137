"""Shared, type-safe identifiers for workflow phase agents.

These replace bare string literals ("claude" / "codex" / "claude-interactive")
that were previously compared in many places across the domain, adapter, and API
layers. `StrEnum` members compare equal to their string value, so a loose
``provider: str`` field can still be compared against a member
(``provider == AgentProvider.CODEX``) without changing the field type.
"""

from __future__ import annotations

from enum import StrEnum


class AgentProvider(StrEnum):
    """A workflow phase's ``agent_config.provider`` value.

    The domain ``provider`` field stays a plain ``str`` (it also accepts
    test-only values like ``"mock"``); these members are the KNOWN production
    providers to compare against, never a bare literal.
    """

    CLAUDE = "claude"
    """Default headless ``claude -p`` docker-exec path."""

    CLAUDE_INTERACTIVE = "claude-interactive"
    """Interactive-tmux pane path (parked hedge, syn137#777)."""

    CODEX = "codex"
    """Headless ``codex exec`` docker-exec path (the codex bridge)."""


class AgentRunner(StrEnum):
    """Which stream processor drives a headless phase (claude vs codex)."""

    CLAUDE = "claude"
    CODEX = "codex"


class ModelAlias(StrEnum):
    """CLI-compatible Claude model aliases.

    The ``claude`` CLI resolves these to the latest dated model in each
    family, so the platform stores the alias rather than pinning a version.
    Never write these as bare literals - issue #793.
    """

    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class ModelId(StrEnum):
    """Canonical model identifiers - the keys of the pricing table.

    An alias (``ModelAlias``) is what a workflow author writes; a ModelId is
    what a price is attached to. Keeping them in separate enums stops the
    two from being used interchangeably, which is how ``"codex"`` - a
    PROVIDER name - once ended up resolving to GPT-5.6 pricing (issue #788).

    Adding a model means adding a member here AND an entry in
    ``syn_shared.pricing.MODEL_PRICING_TABLE``; the table is keyed by this
    enum so a member without a price is a visible gap rather than a silent
    fallback.
    """

    # --- Current generation (ADR-067 phase 0, verified 2026-08-16) ---
    CLAUDE_OPUS_5 = "claude-opus-5"
    CLAUDE_SONNET_5 = "claude-sonnet-5"
    CLAUDE_FABLE_5 = "claude-fable-5"
    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5-20251001"
    GPT_5_6_SOL = "gpt-5.6-sol"
    # --- Previous generation ---
    CLAUDE_OPUS_4_5 = "claude-opus-4-5-20251101"
    CLAUDE_SONNET_4_5 = "claude-sonnet-4-5-20250929"
    # --- Legacy ---
    GPT_5_6 = "gpt-5.6"
    CLAUDE_OPUS_4 = "claude-opus-4-20250514"
    CLAUDE_SONNET_4 = "claude-sonnet-4-20250514"
    CLAUDE_SONNET_3_5 = "claude-3-5-sonnet-20241022"
    CLAUDE_HAIKU_3_5 = "claude-3-5-haiku-20241022"
    CLAUDE_OPUS_3 = "claude-3-opus-20240229"
    CLAUDE_HAIKU_3 = "claude-3-haiku-20240307"


DEFAULT_CLAUDE_MODEL: str = ModelAlias.HAIKU
"""Model a Claude phase runs under when the workflow does not name one.

Haiku keeps unattended/test workflows cheap. This default applies ONLY to
Claude providers: codex does not report its own model on the wire, so a codex
phase without an explicit ``model:`` stays ``None`` (honestly unknown) rather
than inheriting a Claude alias. Synthesizing one is what made every codex run
show up as Haiku in Cost-by-Model - issue #788.

Do not "fix" that by synthesizing the string ``"codex"`` either. An earlier
attempt did, and it propagated as a genuine model id: ``codex exec --model
codex`` names a nonexistent model, and ``resolve_model_pricing("codex")``
confidently returned GPT-5.6 rates for a model we never ran. A confidently
wrong price is invisible in a dashboard; an absent one is at least visibly
missing. ``None`` means "codex ran model-unforced; leave it unpriced until
the real model is known."

Resolution happens in ``AgentConfiguration.__post_init__`` (both copies), NOT
in callers - a caller-side default only covers the paths that caller owns,
which is how the Haiku default survived the first fix.
"""


_CLAUDE_ALIASES: frozenset[str] = frozenset(ModelAlias)


def resolve_phase_model(provider: str, model: str | None) -> str | None:
    """Normalise a phase's model for ``provider``, returning the value to store.

    Both ``AgentConfiguration`` copies call this from ``__post_init__`` so the
    rule lives in exactly one place. Three normalisations, in order:

    1. Blank or whitespace-only means "unset". A workflow with ``model: ""``
       used to be rescued by a caller-side ``phase_model or default``; without
       that, an empty string would reach the CLI as ``--model ""``.
    2. A Claude alias on a CODEX phase is dropped to ``None``. Codex rejects
       Claude models outright, and keeping one is what prices codex runs as
       Haiku (issue #788). This also has to run on ALREADY-RESOLVED input:
       ``dataclasses.replace(claude_config, provider=CODEX)`` re-enters the
       constructor carrying the resolved ``"haiku"``, which no longer looks
       like a default to anything downstream.
    3. An unset model on a non-codex provider gets ``DEFAULT_CLAUDE_MODEL``.

    An explicit non-Claude model is always preserved, so a codex phase that
    names ``gpt-5.6`` keeps it.
    """
    normalised = model.strip() if model is not None else None
    if not normalised:
        normalised = None
    if provider == AgentProvider.CODEX:
        return None if normalised in _CLAUDE_ALIASES else normalised
    return normalised if normalised is not None else DEFAULT_CLAUDE_MODEL
