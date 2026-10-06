"""PC-83: a stored phase's `fallback_agent` resolved at the execution boundary.

A stored template never saw the YAML validator, so the boundary is where the
fallback gets its provider checked, its model resolved for ITS provider, and
the codex tool-policy refusal - and where it inherits the primary's tools,
sandbox and delegation, so a fallback run cannot do more than the phase could.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    FallbackAgent,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    UnsupportedToolPolicyForProviderError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    _build_agent_config_from_phase,
    _fallback_agent_config,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    _codex_auth_staged_for,
)
from syn_shared.agents import DEFAULT_CODEX_MODEL, AgentProvider

pytestmark = pytest.mark.unit


def _phase(fallback: FallbackAgent | None, **declared: object) -> PhaseDefinition:
    return PhaseDefinition.model_validate(
        {
            "phase_id": "verify",
            "name": "verify",
            "order": 1,
            "prompt_template": "x",
            "fallback_agent": fallback,
            **declared,
        }
    )


def test_no_declaration_is_no_fallback() -> None:
    phase = _phase(None)
    assert _fallback_agent_config(phase, _build_agent_config_from_phase(phase)) is None


def test_the_fallback_keeps_the_phases_policy_and_resolves_its_own_model() -> None:
    phase = _phase(FallbackAgent(provider="codex"), sandbox="read-only")
    primary = _build_agent_config_from_phase(phase)

    fallback = _fallback_agent_config(phase, primary)

    assert fallback is not None
    assert fallback.provider == AgentProvider.CODEX
    assert fallback.model == DEFAULT_CODEX_MODEL, "inherited the primary's claude model"
    assert fallback.sandbox == primary.sandbox == "read-only"


def test_a_codex_fallback_on_a_tool_scoped_phase_is_refused() -> None:
    phase = _phase(FallbackAgent(provider="codex"), allowed_tools=["Read"])

    with pytest.raises(UnsupportedToolPolicyForProviderError):
        _fallback_agent_config(phase, _build_agent_config_from_phase(phase))


def test_a_codex_fallback_stages_codex_auth_in_a_claude_phase() -> None:
    from dataclasses import replace

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        AgentConfiguration,
        ExecutablePhase,
    )

    claude_only = ExecutablePhase(phase_id="p", name="p", order=1)
    with_codex = replace(
        claude_only, fallback_agent=AgentConfiguration(provider=AgentProvider.CODEX)
    )

    assert _codex_auth_staged_for(claude_only) is False
    assert _codex_auth_staged_for(with_codex) is True
