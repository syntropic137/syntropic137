"""Alias -> concrete model id, the one table every surface reads.

Definition surfaces show ``gpt-sol → gpt-6-sol``; the codex command builder
forces the same slug; pricing prices the same id. These tests pin that all
three read ONE map, so a generation swap cannot move one and strand the rest.
"""

from __future__ import annotations

import pytest

from syn_shared.agents import (
    CLAUDE_MODEL_ALIAS_TARGETS,
    CODEX_MODEL_ALIAS_TARGETS,
    AliasResolutionBasis,
    CodexModelAlias,
    ModelAlias,
    ModelId,
    resolve_codex_model_alias,
    resolve_model_alias,
)
from syn_shared.display import ALIAS_ARROW, EM_DASH, format_model_definition
from syn_shared.pricing import MODEL_ALIASES, canonical_model_id

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("alias", "target", "basis"),
    [
        ("gpt-sol", ModelId.GPT_6_SOL, AliasResolutionBasis.TRANSLATED),
        ("opus", ModelId.CLAUDE_OPUS_5_5, AliasResolutionBasis.EXPECTED),
        ("sonnet", ModelId.CLAUDE_SONNET_5, AliasResolutionBasis.EXPECTED),
        ("haiku", ModelId.CLAUDE_HAIKU_4_5, AliasResolutionBasis.EXPECTED),
        ("fable", ModelId.CLAUDE_FABLE_5, AliasResolutionBasis.EXPECTED),
    ],
)
def test_each_alias_resolves(alias: str, target: ModelId, basis: AliasResolutionBasis) -> None:
    resolution = resolve_model_alias(alias)
    assert resolution is not None
    assert resolution.alias == alias
    assert resolution.target == target
    assert resolution.basis == basis


@pytest.mark.parametrize(
    "model",
    [
        "gpt-6-sol",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "not-a-model",
        "Opus",  # aliases are case-sensitive: the CLI would not accept this either
        "",
        None,
    ],
)
def test_non_aliases_do_not_resolve(model: str | None) -> None:
    assert resolve_model_alias(model) is None


def test_every_alias_has_exactly_one_target() -> None:
    assert set(CLAUDE_MODEL_ALIAS_TARGETS) == set(ModelAlias)
    assert set(CODEX_MODEL_ALIAS_TARGETS) == set(CodexModelAlias)


@pytest.mark.parametrize("alias", sorted({*ModelAlias, *CodexModelAlias}))
def test_pricing_and_the_codex_command_agree_with_the_resolver(alias: str) -> None:
    resolution = resolve_model_alias(alias)
    assert resolution is not None
    assert MODEL_ALIASES[alias] == resolution.target
    assert canonical_model_id(alias) == resolution.target
    if resolution.basis is AliasResolutionBasis.TRANSLATED:
        assert resolve_codex_model_alias(alias) == resolution.target
    else:
        # A claude alias reaches the CLI verbatim; only codex is translated.
        assert resolve_codex_model_alias(alias) == alias


class TestFormatModelDefinition:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("gpt-sol", "gpt-sol → gpt-6-sol"),
            ("opus", "opus → claude-opus-5-5"),
            ("sonnet", "sonnet → claude-sonnet-5"),
            ("haiku", "haiku → claude-haiku-4-5-20251001"),
            ("fable", "fable → claude-fable-5"),
        ],
    )
    def test_alias_shows_its_target(self, model: str, expected: str) -> None:
        assert format_model_definition(model) == expected

    @pytest.mark.parametrize("model", ["gpt-6-sol", "claude-opus-5-5", "some-future-model"])
    def test_concrete_and_unknown_round_trip(self, model: str) -> None:
        assert format_model_definition(model) == model

    def test_none_stays_none(self) -> None:
        assert format_model_definition(None) is None

    def test_uses_an_arrow_never_an_em_dash(self) -> None:
        rendered = format_model_definition("opus")
        assert rendered is not None
        assert ALIAS_ARROW in rendered
        assert EM_DASH not in rendered
