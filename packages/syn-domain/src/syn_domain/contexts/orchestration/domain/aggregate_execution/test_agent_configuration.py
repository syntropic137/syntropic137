"""Tests for AgentConfiguration invariants.

The provider/agent_id guard that used to live here went away with the
interactive-tmux excision: ``agent_id`` only ever named a tmux pane, so
with that path gone there is no combination left to reject.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
)
from syn_shared.agents import DEFAULT_CODEX_MODEL, AgentProvider


@pytest.mark.unit
class TestAgentConfigurationProviders:
    def test_default_provider_is_claude(self) -> None:
        assert AgentConfiguration().provider == AgentProvider.CLAUDE

    def test_codex_provider_constructs(self) -> None:
        config = AgentConfiguration(provider=AgentProvider.CODEX)
        assert config.provider == AgentProvider.CODEX

    def test_codex_phase_gets_the_codex_default_not_a_claude_one(self) -> None:
        """A codex phase with no model gets gpt-sol, never Haiku (#788)."""
        assert AgentConfiguration(provider=AgentProvider.CODEX).model == DEFAULT_CODEX_MODEL


@pytest.mark.unit
class TestAgentConfigurationFrozen:
    def test_still_frozen(self) -> None:
        config = AgentConfiguration(provider=AgentProvider.CODEX)
        with pytest.raises(Exception):  # noqa: B017 - dataclasses.FrozenInstanceError
            config.provider = "claude"  # type: ignore[misc]
