"""Every alias a workflow author may write must resolve to a real price.

An alias is the mechanism that lets workflows survive a model release without
being edited: `model: sonnet` kept working when Sonnet 5 shipped. That only
holds if the alias is wired in BOTH places:

    ModelAlias        - the name an author is allowed to write
    MODEL_ALIASES     - the map from that name to a priced ModelId

Adding a member to the first without the second is silent. The workflow still
runs, the model still resolves, and the cost comes back UNPRICED - which looks
identical to a free run unless someone checks unpriced_observation_count.
That is exactly how `fable` shipped as a usable alias with no price attached.

These tests fail the build instead, so the gap is caught at the moment the
alias is added rather than in a cost report weeks later.
"""

from __future__ import annotations

import pytest

from syn_shared.agents import ModelAlias, ModelId, resolve_phase_model
from syn_shared.pricing import MODEL_ALIASES, MODEL_PRICING_TABLE, resolve_model_pricing


@pytest.mark.unit
class TestEveryAliasIsPriced:
    def test_every_alias_maps_to_a_model_id(self) -> None:
        missing = [a.value for a in ModelAlias if a not in MODEL_ALIASES]
        assert not missing, (
            f"ModelAlias members with no MODEL_ALIASES entry: {missing}. "
            "An author can write these and get an unpriced run."
        )

    def test_every_alias_resolves_to_a_real_price(self) -> None:
        unpriced = [a.value for a in ModelAlias if resolve_model_pricing(a.value) is None]
        assert not unpriced, f"aliases that resolve to no price: {unpriced}"

    def test_every_alias_target_has_a_pricing_table_entry(self) -> None:
        """Guards the second hop: alias -> ModelId -> rate."""
        orphans = [
            (alias, target.value)
            for alias, target in MODEL_ALIASES.items()
            if target not in MODEL_PRICING_TABLE
        ]
        assert not orphans, f"alias targets absent from MODEL_PRICING_TABLE: {orphans}"

    @pytest.mark.parametrize("alias", [a.value for a in ModelAlias])
    def test_alias_prices_are_positive(self, alias: str) -> None:
        """A zero rate is indistinguishable from a free model downstream."""
        pricing = resolve_model_pricing(alias)
        assert pricing is not None
        assert pricing.input_per_million > 0
        assert pricing.output_per_million > 0


@pytest.mark.unit
class TestAliasesAreClaudeOnly:
    """Every ModelAlias is a Claude alias, and codex must drop all of them.

    `_CLAUDE_ALIASES` derives from the ModelAlias enum, so this holds
    automatically - the test exists to keep it that way. If an OpenAI alias is
    ever added to ModelAlias, this fails and forces the drop-rule to be
    revisited rather than silently swallowing a valid codex model (issue #788).
    """

    @pytest.mark.parametrize("alias", [a.value for a in ModelAlias])
    def test_codex_phase_drops_every_claude_alias(self, alias: str) -> None:
        assert resolve_phase_model("codex", alias) is None

    @pytest.mark.parametrize("alias", [a.value for a in ModelAlias])
    def test_claude_phase_preserves_every_alias(self, alias: str) -> None:
        assert resolve_phase_model("claude", alias) == alias

    def test_every_alias_target_is_a_claude_model(self) -> None:
        non_claude = [
            (a.value, MODEL_ALIASES[a].value)
            for a in ModelAlias
            if a in MODEL_ALIASES and not MODEL_ALIASES[a].value.startswith("claude-")
        ]
        assert not non_claude, (
            f"ModelAlias members pointing at non-Claude models: {non_claude}. "
            "Codex drops every ModelAlias, so such an alias would be unusable."
        )


@pytest.mark.unit
class TestKnownModelsArePriced:
    """Any ModelId we bothered to name must carry a rate.

    A member without a table entry is a model the platform believes exists but
    cannot cost, which surfaces as a silently unpriced run.
    """

    def test_no_model_id_lacks_pricing(self) -> None:
        missing = [m.value for m in ModelId if m not in MODEL_PRICING_TABLE]
        assert not missing, f"ModelId members with no price: {missing}"
