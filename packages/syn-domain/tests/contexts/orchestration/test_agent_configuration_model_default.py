"""Per-provider model defaulting on AgentConfiguration (issue #788).

Codex phases must never inherit a Claude alias. The first fix at
`_build_agent_config_from_phase` only covered configs built from a YAML
phase, leaving `model = "haiku"` as the declared default on both value
objects - so any other construction path still produced a codex config
attributed to Haiku. Resolution now lives in `__post_init__`, and these
tests pin that for BOTH copies of the value object.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import (
    AgentConfiguration as SharedAgentConfiguration,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration as AggregateAgentConfiguration,
)
from syn_shared.agents import DEFAULT_CLAUDE_MODEL, AgentProvider, ModelAlias, ModelId

# Both copies are kept in sync by hand; every case runs against both so a
# drifting copy fails loudly instead of silently keeping the old default.
CONFIGS = [SharedAgentConfiguration, AggregateAgentConfiguration]


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_codex_without_explicit_model_stays_unknown(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """A codex config built directly - not via a YAML phase - must not be Haiku."""
    config = config_cls(provider=AgentProvider.CODEX)

    assert config.model is None


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_codex_keeps_an_explicit_model(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """Naming a model on a codex phase is honoured, not overwritten."""
    config = config_cls(provider=AgentProvider.CODEX, model="gpt-5.6")

    assert config.model == "gpt-5.6"


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_claude_without_explicit_model_gets_the_shared_default(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """Back-compat: an unqualified Claude phase still runs the cheap default."""
    config = config_cls()

    assert config.provider == AgentProvider.CLAUDE
    assert config.model == DEFAULT_CLAUDE_MODEL
    assert config.model == ModelAlias.HAIKU


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_claude_keeps_an_explicit_model(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """An explicit Claude alias is not clobbered by the default."""
    config = config_cls(model=ModelAlias.OPUS)

    assert config.model == ModelAlias.OPUS


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_replace_onto_codex_drops_the_resolved_claude_model(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """`replace()` re-enters the constructor with an ALREADY-RESOLVED model.

    Second-pass review finding: `__post_init__` cannot tell a defaulted
    "haiku" from an explicitly chosen one, so switching a Claude config to
    codex via `dataclasses.replace` carried Haiku across and recreated the
    exact #788 bug. Resolution now drops Claude aliases on codex phases
    whether they arrived as a default or explicitly.
    """
    claude_config = config_cls()
    assert claude_config.model == DEFAULT_CLAUDE_MODEL

    codex_config = replace(claude_config, provider=AgentProvider.CODEX)

    assert codex_config.model is None


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_replace_onto_codex_keeps_a_real_codex_model(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """Dropping Claude aliases must not drop a genuine codex model."""
    codex_config = replace(config_cls(), provider=AgentProvider.CODEX, model=ModelId.GPT_5_6)

    assert codex_config.model == ModelId.GPT_5_6


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_replace_back_to_claude_restores_the_default(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """Going codex -> claude with no model resolves the Claude default again."""
    codex_config = config_cls(provider=AgentProvider.CODEX)

    claude_config = replace(codex_config, provider=AgentProvider.CLAUDE)

    assert claude_config.model == DEFAULT_CLAUDE_MODEL


@pytest.mark.parametrize("config_cls", CONFIGS)
def test_resolved_config_equals_a_directly_constructed_one(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
) -> None:
    """`object.__setattr__` in __post_init__ must not break equality or hashing."""
    via_replace = replace(config_cls(), provider=AgentProvider.CODEX)
    direct = config_cls(provider=AgentProvider.CODEX)

    assert via_replace == direct
    assert hash(via_replace) == hash(direct)


@pytest.mark.parametrize("config_cls", CONFIGS)
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_model_is_treated_as_unset(
    config_cls: type[SharedAgentConfiguration] | type[AggregateAgentConfiguration],
    blank: str,
) -> None:
    """`model: ""` must not reach the CLI as `--model ""`.

    Second-pass review finding: the old caller used `phase_model or default`,
    which swallowed empty strings. Passing `phase_model` straight through let
    them past, since `__post_init__` only defaulted None.
    """
    assert config_cls(model=blank).model == DEFAULT_CLAUDE_MODEL
    assert config_cls(provider=AgentProvider.CODEX, model=blank).model is None
