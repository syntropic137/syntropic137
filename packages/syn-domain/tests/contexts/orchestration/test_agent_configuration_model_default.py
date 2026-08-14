"""Per-provider model defaulting on AgentConfiguration (issue #788).

Codex phases must never inherit a Claude alias. The first fix at
`_build_agent_config_from_phase` only covered configs built from a YAML
phase, leaving `model = "haiku"` as the declared default on both value
objects - so any other construction path still produced a codex config
attributed to Haiku. Resolution now lives in `__post_init__`, and these
tests pin that for BOTH copies of the value object.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import (
    AgentConfiguration as SharedAgentConfiguration,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration as AggregateAgentConfiguration,
)
from syn_shared.agents import DEFAULT_CLAUDE_MODEL, AgentProvider, ModelAlias

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
