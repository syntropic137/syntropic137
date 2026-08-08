"""Tests for AgentConfiguration's provider/agent_id invariant (codex bridge).

Covers the must-fix codex-review finding: `provider="codex"` must never
silently pair with `agent_id="claude"`. `agent_id` now defaults to `None`
(distinguishable from an explicit "claude" tmux-pane selection) and a
`__post_init__` guard rejects nonsensical provider/agent_id combinations.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
)


class TestAgentConfigurationDefaults:
    def test_default_agent_id_is_none_not_claude(self) -> None:
        """agent_id must be None by default - distinguishable from 'claude'."""
        config = AgentConfiguration()
        assert config.agent_id is None
        assert config.provider == "claude"

    def test_claude_provider_with_no_agent_id_still_constructs(self) -> None:
        """Existing claude phases (PR #765) keep constructing with agent_id unset."""
        config = AgentConfiguration(provider="claude")
        assert config.agent_id is None

    def test_claude_interactive_with_no_agent_id_still_constructs(self) -> None:
        """claude-interactive is unrelated to the codex guard - agent_id=None is fine."""
        config = AgentConfiguration(provider="claude-interactive")
        assert config.agent_id is None

    def test_claude_interactive_with_explicit_agent_id_unchanged(self) -> None:
        config = AgentConfiguration(provider="claude-interactive", agent_id="codex")
        assert config.agent_id == "codex"


class TestAgentConfigurationCodexProvider:
    def test_codex_provider_with_no_agent_id_constructs(self) -> None:
        """provider='codex' with agent_id omitted must NOT default to 'claude'."""
        config = AgentConfiguration(provider="codex")
        assert config.provider == "codex"
        assert config.agent_id is None

    def test_codex_provider_with_explicit_codex_agent_id_constructs(self) -> None:
        config = AgentConfiguration(provider="codex", agent_id="codex")
        assert config.agent_id == "codex"

    def test_codex_provider_with_claude_agent_id_raises(self) -> None:
        """The must-fix regression: codex provider must never pair with agent_id='claude'."""
        with pytest.raises(ValueError, match="codex"):
            AgentConfiguration(provider="codex", agent_id="claude")

    def test_codex_provider_with_gemini_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="codex"):
            AgentConfiguration(provider="codex", agent_id="gemini")


class TestAgentConfigurationFrozen:
    def test_still_frozen(self) -> None:
        config = AgentConfiguration(provider="codex")
        with pytest.raises(Exception):  # noqa: B017 - dataclasses.FrozenInstanceError
            config.provider = "claude"  # type: ignore[misc]
