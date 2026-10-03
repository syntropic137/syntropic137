"""Pin the Opus 5.5 and GPT-6-Sol rates field by field (read 2026-09-24).

Same discipline as ``test_openai_published_rates``: the numbers are
transcribed from the vendor pages and asserted literally, so a diff here is
read against the page rather than reasoned about from the code.

Opus 5.5 is the case the old table header got wrong by construction. The
header said "cache read 0.10x of input" for every Claude row; Opus 5.5 reads
at $0.20 on a $4.00 input, which is 0.05x. Deriving it would have billed cache
reads at twice the published rate.

GPT-6-Sol publishes no cache-write rate. The table's codex convention (1.25x
input) supplies one, and the test says so rather than presenting it as
published.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_shared.agents import (
    CODEX_MODEL_ALIAS_TARGETS,
    CodexModelAlias,
    ModelAlias,
    ModelId,
    resolve_codex_model_alias,
)
from syn_shared.pricing import price_tokens, resolve_model_pricing

#: (input, 5-min cache write, cache read, output) in USD per million tokens.
OPUS_5_5_PUBLISHED = ("4.00", "5.00", "0.20", "20.00")

#: (input, cached input, output) in USD per million tokens, short context,
#: Standard tier. Cache write is not published.
GPT_6_SOL_PUBLISHED = ("2.00", "0.20", "10.00")
GPT_6_SOL_CACHE_WRITE_BY_CONVENTION = "2.50"


@pytest.mark.unit
class TestOpus55:
    def test_every_field_matches_the_vendor_page(self) -> None:
        pricing = resolve_model_pricing(ModelId.CLAUDE_OPUS_5_5)
        assert pricing is not None
        expected_input, expected_write, expected_read, expected_output = OPUS_5_5_PUBLISHED
        assert pricing.input_per_million == Decimal(expected_input)
        assert pricing.cache_creation_per_million == Decimal(expected_write)
        assert pricing.cache_read_per_million == Decimal(expected_read)
        assert pricing.output_per_million == Decimal(expected_output)

    def test_cache_read_is_not_the_blanket_tenth_of_input(self) -> None:
        """Guard the specific wrong derivation the old header invited."""
        pricing = resolve_model_pricing(ModelId.CLAUDE_OPUS_5_5)
        assert pricing is not None
        assert pricing.cache_read_per_million != pricing.input_per_million * Decimal("0.10")

    def test_opus_alias_prices_as_opus_5_5(self) -> None:
        pricing = resolve_model_pricing(ModelAlias.OPUS)
        assert pricing is not None
        assert pricing.model_id is ModelId.CLAUDE_OPUS_5_5

    def test_the_id_the_cli_reports_prices_directly(self) -> None:
        """claude-code 2.1.281 reports exactly ``claude-opus-5-5`` (probed)."""
        priced = price_tokens("claude-opus-5-5", 1_000_000, 1_000_000, 1_000_000, 1_000_000)
        assert priced.model == ModelId.CLAUDE_OPUS_5_5
        assert priced.cost == Decimal("4.00") + Decimal("20.00") + Decimal("5.00") + Decimal("0.20")


@pytest.mark.unit
class TestGpt6Sol:
    def test_every_published_field_matches(self) -> None:
        pricing = resolve_model_pricing(ModelId.GPT_6_SOL)
        assert pricing is not None
        expected_input, expected_cached, expected_output = GPT_6_SOL_PUBLISHED
        assert pricing.input_per_million == Decimal(expected_input)
        assert pricing.cache_read_per_million == Decimal(expected_cached)
        assert pricing.output_per_million == Decimal(expected_output)

    def test_cache_write_follows_the_codex_convention(self) -> None:
        pricing = resolve_model_pricing(ModelId.GPT_6_SOL)
        assert pricing is not None
        assert pricing.cache_creation_per_million == Decimal(GPT_6_SOL_CACHE_WRITE_BY_CONVENTION)
        assert pricing.cache_creation_per_million == pricing.input_per_million * Decimal("1.25")

    def test_gpt_sol_alias_prices_as_gpt_6_sol(self) -> None:
        """The requested-model path sees the stored alias, not the slug."""
        alias = resolve_model_pricing(CodexModelAlias.GPT_SOL)
        concrete = resolve_model_pricing(ModelId.GPT_6_SOL)
        assert alias is not None
        assert alias is concrete


@pytest.mark.unit
class TestCodexAliasTranslation:
    def test_every_codex_alias_has_a_target(self) -> None:
        assert set(CODEX_MODEL_ALIAS_TARGETS) == set(CodexModelAlias)

    def test_every_codex_alias_target_is_priced(self) -> None:
        for alias, target in CODEX_MODEL_ALIAS_TARGETS.items():
            assert resolve_model_pricing(target) is not None, alias

    def test_gpt_sol_translates_to_gpt_6_sol(self) -> None:
        assert resolve_codex_model_alias(CodexModelAlias.GPT_SOL) == ModelId.GPT_6_SOL

    def test_a_concrete_slug_passes_through(self) -> None:
        assert resolve_codex_model_alias(ModelId.GPT_5_6_SOL) == ModelId.GPT_5_6_SOL

    def test_codex_aliases_are_not_claude_aliases(self) -> None:
        """A codex phase drops every ModelAlias, so overlap would drop gpt-sol."""
        assert not ({str(a) for a in CodexModelAlias} & {str(a) for a in ModelAlias})


@pytest.mark.unit
class TestModelFamilies:
    def test_the_two_families_partition_model_id(self) -> None:
        """A new ModelId must declare which harness runs it."""
        from syn_shared.agents import CLAUDE_MODEL_IDS, CODEX_MODEL_IDS

        assert not CLAUDE_MODEL_IDS & CODEX_MODEL_IDS
        assert set(ModelId) == CLAUDE_MODEL_IDS | CODEX_MODEL_IDS

    def test_unknown_strings_are_not_judged(self) -> None:
        from syn_shared.agents import AgentProvider, model_is_for_provider

        assert model_is_for_provider("gpt-future-slug", AgentProvider.CLAUDE) is None
        assert model_is_for_provider(ModelId.GPT_6_SOL, AgentProvider.CLAUDE) is False
        assert model_is_for_provider(ModelId.GPT_6_SOL, AgentProvider.CODEX) is True
