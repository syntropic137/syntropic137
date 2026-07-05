"""Unit tests for `_is_interactive_phase` (issue #771 item 5).

`WorkspaceProvisionHandler._is_interactive_phase` used to OR together an
explicit signal (`phase.agent_config.provider == "claude-interactive"`)
with an implicit one (`workspace.isolation_handle.isolation_type ==
"interactive-tmux"`) on the theory that the YAML schema had no
`agent.provider` field. That has been false since PR #765. These tests
pin the collapsed, explicit-only behaviour and the new mismatch guard
that replaces the silent implicit fallback.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    WorkspaceMisconfiguredError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    _is_interactive_phase,
    _provisioned_agents,
)


def _phase(provider: str, agent_id: str = "claude") -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="p1",
        name="Phase 1",
        order=1,
        agent_config=AgentConfiguration(provider=provider, agent_id=agent_id),
        prompt_template="do it",
    )


def _workspace(isolation_type: str) -> MagicMock:
    workspace = MagicMock()
    workspace.isolation_handle.isolation_type = isolation_type
    return workspace


class TestIsInteractivePhaseExplicitOnly:
    """Explicit `provider="claude-interactive"` is the only interactive signal."""

    def test_explicit_interactive_on_interactive_workspace(self) -> None:
        workspace = _workspace("interactive-tmux")
        assert _is_interactive_phase(workspace, _phase("claude-interactive")) is True

    def test_default_provider_on_docker_workspace(self) -> None:
        workspace = _workspace("docker")
        assert _is_interactive_phase(workspace, _phase("claude")) is False

    def test_implicit_isolation_type_no_longer_flips_result(self) -> None:
        """A `claude` phase landing on a docker workspace is unambiguous.

        This is the base case the old implicit-detection comment claimed
        was unreachable; it is exercised directly here for clarity, and by
        the docker-workspace fixture in every other test in this class.
        """
        workspace = _workspace("docker")
        assert _is_interactive_phase(workspace, _phase("claude")) is False


class TestIsInteractivePhaseMismatchGuard:
    """Explicit signal disagreeing with the workspace's backend fails loudly."""

    def test_interactive_phase_on_non_interactive_workspace_raises(self) -> None:
        """An interactive phase must never silently run on a docker workspace.

        Previously the implicit OR made this combination resolve to
        ``False`` (docker path) with no signal that anything was wrong.
        """
        workspace = _workspace("docker")
        with pytest.raises(WorkspaceMisconfiguredError, match="claude-interactive"):
            _is_interactive_phase(workspace, _phase("claude-interactive"))

    def test_non_interactive_phase_on_interactive_workspace_raises(self) -> None:
        """A plain `claude` phase must never silently run against a tmux workspace.

        Previously the implicit OR flipped this to ``True`` (interactive
        path) even though the phase never asked for it.
        """
        workspace = _workspace("interactive-tmux")
        with pytest.raises(WorkspaceMisconfiguredError, match="interactive-tmux"):
            _is_interactive_phase(workspace, _phase("claude"))


class TestProvisionedAgents:
    """Interactive phases provision only the agent they drive."""

    def test_interactive_phase_provisions_only_its_agent(self) -> None:
        assert _provisioned_agents(_phase("claude-interactive", "claude")) == ("claude",)

    def test_interactive_phase_honors_non_claude_agent(self) -> None:
        # Forward-compatible: a codex/gemini interactive phase stages that agent.
        assert _provisioned_agents(_phase("claude-interactive", "codex")) == ("codex",)

    def test_docker_phase_provisions_no_specific_agent(self) -> None:
        # Empty -> the docker backend ignores it and the interactive provider
        # would fall back to all agents (not reachable on the docker path).
        assert _provisioned_agents(_phase("claude", "claude")) == ()
