"""Tests for opt-in codex<->claude delegation: schema, config, auth staging, note."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
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


# === B4: delegation note (provider-aware, both directions) ===


def test_delegation_note_codex_primary_targets_claude() -> None:
    note = WorkspaceProvisionHandler._delegation_note(AgentProvider.CODEX, True)
    assert "claude -p" in note
    assert "delegating-to-claude-p" in note


def test_delegation_note_claude_primary_targets_codex() -> None:
    note = WorkspaceProvisionHandler._delegation_note(AgentProvider.CLAUDE, True)
    assert "codex exec" in note
    assert "delegating-to-codex" in note


def test_no_delegation_note_when_disabled() -> None:
    assert WorkspaceProvisionHandler._delegation_note(AgentProvider.CODEX, False) == ""
    assert WorkspaceProvisionHandler._delegation_note(AgentProvider.CLAUDE, False) == ""


# === B4 delivery integration: note reaches both files even with no repos ===


def test_delegation_note_injected_into_both_files_no_repos() -> None:
    note = WorkspaceProvisionHandler._delegation_note(AgentProvider.CODEX, True)
    files = WorkspaceProvisionHandler._context_files([], note)
    names = {name for name, _ in files}
    assert names == {"AGENTS.md", "CLAUDE.md"}
    for _, content in files:
        assert b"claude -p" in content


def test_no_files_injected_when_no_repos_and_no_delegation() -> None:
    assert WorkspaceProvisionHandler._context_files([], "") == []
