"""Tests for the `_shared.ExecutionValueObjects.AgentConfiguration` mirror.

This module duplicates `aggregate_execution.value_objects.AgentConfiguration`
(see that module's docstring for why the duplication exists). The codex
bridge invariant - `agent_id` defaults to `None`, and `provider="codex"`
paired with an unrelated `agent_id` is rejected - must hold in BOTH mirrors
identically so neither one silently regresses to the old
`agent_id="claude"` default.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import (
    AgentConfiguration,
)


class TestExecutionValueObjectsAgentConfigurationDefaults:
    def test_default_agent_id_is_none_not_claude(self) -> None:
        config = AgentConfiguration()
        assert config.agent_id is None
        assert config.provider == "claude"

    def test_claude_interactive_with_explicit_agent_id_unchanged(self) -> None:
        config = AgentConfiguration(provider="claude-interactive", agent_id="codex")
        assert config.agent_id == "codex"


class TestExecutionValueObjectsAgentConfigurationCodexProvider:
    def test_codex_provider_with_no_agent_id_constructs(self) -> None:
        config = AgentConfiguration(provider="codex")
        assert config.provider == "codex"
        assert config.agent_id is None

    def test_codex_provider_with_explicit_codex_agent_id_constructs(self) -> None:
        config = AgentConfiguration(provider="codex", agent_id="codex")
        assert config.agent_id == "codex"

    def test_codex_provider_with_claude_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="codex"):
            AgentConfiguration(provider="codex", agent_id="claude")

    def test_codex_provider_with_gemini_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="codex"):
            AgentConfiguration(provider="codex", agent_id="gemini")
