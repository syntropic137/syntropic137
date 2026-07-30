"""Tests for opt-in codex<->claude delegation: schema, config, auth staging, note."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    _build_agent_config_from_phase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
    _auth_staging_for,
)
from syn_shared.agents import AgentProvider

_YAML = """
id: deleg-test
name: Delegation Test
type: research
classification: simple
requires_repos: false
phases:
  - id: p1
    name: Codex with delegation
    order: 1
    prompt_template: do the thing
    agent:
      provider: codex
      allow_delegation: true
"""


# === B1: schema -> domain phase ===


def test_allow_delegation_flows_to_domain_phase() -> None:
    phase = WorkflowDefinition.from_yaml(_YAML).get_domain_phases()[0]
    assert phase.provider == AgentProvider.CODEX
    assert phase.allow_delegation is True


def test_allow_delegation_defaults_false() -> None:
    yaml = _YAML.replace("      allow_delegation: true\n", "")
    phase = WorkflowDefinition.from_yaml(yaml).get_domain_phases()[0]
    assert phase.allow_delegation is False


def test_allow_delegation_rejected_for_interactive() -> None:
    yaml = _YAML.replace("provider: codex", "provider: claude-interactive")
    with pytest.raises(ValueError, match="headless"):
        WorkflowDefinition.from_yaml(yaml)


# === B2: agent config ===


def test_agent_config_carries_allow_delegation() -> None:
    phase = PhaseDefinition(
        phase_id="p1",
        name="p",
        order=1,
        prompt_template="x",
        provider=AgentProvider.CODEX,
        allow_delegation=True,
    )
    cfg = _build_agent_config_from_phase(phase)
    assert cfg.provider == AgentProvider.CODEX
    assert cfg.allow_delegation is True


# === Issue #788: codex phases must not inherit the claude default model ===


def test_codex_phase_without_explicit_model_does_not_default_to_haiku() -> None:
    """A codex phase that omits `model:` (the common/recommended case, see
    workflows/examples/codex-demo.yaml) must not silently resolve to the
    claude "haiku" default - that mispriced every codex phase with claude
    haiku rates (#788).

    It also must not resolve to a synthesized "codex" model string (the
    original #788 fix's over-correction): that string then flowed into
    `codex exec --model codex` (a nonexistent model) and got confidently
    priced as GPT-5.6 via a pricing alias, despite the real model being
    unknown. The honest state is `None` - unforced model, unpriced cost.
    """
    phase = PhaseDefinition(
        phase_id="p1",
        name="p",
        order=1,
        prompt_template="x",
        provider=AgentProvider.CODEX,
    )
    cfg = _build_agent_config_from_phase(phase)
    assert cfg.model != "haiku"
    assert cfg.model is None


def test_claude_phase_without_explicit_model_still_defaults_to_haiku() -> None:
    """The claude default model is unchanged for claude-provider phases."""
    phase = PhaseDefinition(
        phase_id="p1",
        name="p",
        order=1,
        prompt_template="x",
        provider=AgentProvider.CLAUDE,
    )
    cfg = _build_agent_config_from_phase(phase)
    assert cfg.model == "haiku"


def test_codex_phase_explicit_model_override_is_preserved() -> None:
    """An explicit `model:` on a codex phase still wins over the default."""
    phase = PhaseDefinition(
        phase_id="p1",
        name="p",
        order=1,
        prompt_template="x",
        provider=AgentProvider.CODEX,
        model="gpt-5.6",
    )
    cfg = _build_agent_config_from_phase(phase)
    assert cfg.model == "gpt-5.6"


# === B3: auth staging ===


def test_codex_phase_no_delegation_stages_codex_only() -> None:
    assert _auth_staging_for(AgentProvider.CODEX, False, False) == (True, False)


def test_claude_phase_no_delegation_stages_claude_only() -> None:
    assert _auth_staging_for(AgentProvider.CLAUDE, False, False) == (False, True)


def test_delegation_stages_both_regardless_of_provider() -> None:
    assert _auth_staging_for(AgentProvider.CODEX, True, False) == (True, True)
    assert _auth_staging_for(AgentProvider.CLAUDE, True, False) == (True, True)


def test_interactive_never_needs_claude_env() -> None:
    assert _auth_staging_for(AgentProvider.CLAUDE, True, True)[1] is False


# === B4: baked delegation skill install (rides #772's `skills add`) ===


class _FakeResult:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.stdout = ""
        self.stderr = ""


class _RecordingWorkspace:
    """Minimal workspace double that records `execute` calls."""

    workspace_id = "ws-test"

    def __init__(self, exit_code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._exit_code = exit_code

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
    ) -> _FakeResult:
        self.calls.append(command)
        return _FakeResult(self._exit_code)


def _phase(provider: str, allow_delegation: bool, agent_id: str | None = None) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="p1",
        name="p",
        order=1,
        agent_config=AgentConfiguration(
            provider=provider, allow_delegation=allow_delegation, agent_id=agent_id
        ),
    )


async def test_stray_agent_id_ignored_provider_wins() -> None:
    # provider=claude with a stray agent_id=codex (permitted by YAML validation)
    # must install for claude-code, not codex (the phase runs claude -p).
    ws = _RecordingWorkspace()
    await WorkspaceProvisionHandler._install_baked_delegation_skill(
        ws,
        _phase(AgentProvider.CLAUDE, True, agent_id="codex"),  # type: ignore[arg-type]
    )
    cmd = ws.calls[0]
    assert cmd[2].endswith("delegating-to-codex")
    assert cmd[3:5] == ["--agent", "claude-code"]


async def test_codex_phase_installs_delegating_to_claude_skill() -> None:
    ws = _RecordingWorkspace()
    await WorkspaceProvisionHandler._install_baked_delegation_skill(
        ws, _phase(AgentProvider.CODEX, True)
    )  # type: ignore[arg-type]
    assert len(ws.calls) == 1
    cmd = ws.calls[0]
    assert cmd[:2] == ["skills", "add"]
    assert cmd[2] == "/opt/agentic/plugins/delegation/skills/delegating-to-claude-p"
    assert cmd[3:5] == ["--agent", "codex"]


async def test_claude_phase_installs_delegating_to_codex_skill() -> None:
    ws = _RecordingWorkspace()
    await WorkspaceProvisionHandler._install_baked_delegation_skill(
        ws, _phase(AgentProvider.CLAUDE, True)
    )  # type: ignore[arg-type]
    assert len(ws.calls) == 1
    cmd = ws.calls[0]
    assert cmd[2] == "/opt/agentic/plugins/delegation/skills/delegating-to-codex"
    assert cmd[3:5] == ["--agent", "claude-code"]


async def test_no_install_when_delegation_disabled() -> None:
    ws = _RecordingWorkspace()
    await WorkspaceProvisionHandler._install_baked_delegation_skill(
        ws, _phase(AgentProvider.CODEX, False)
    )  # type: ignore[arg-type]
    assert ws.calls == []
