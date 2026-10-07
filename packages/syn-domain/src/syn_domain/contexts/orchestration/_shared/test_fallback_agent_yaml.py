"""A phase's ``fallback_agent`` is validated at install like ``agent`` is (PC-83).

The phase's tools and budget bind whichever agent runs it, so a provider that
cannot honour them is refused as a fallback for the same reason it is refused
as the primary: #1009 (codex has no tool vocabulary) and #1376 (codex cannot
be stopped by a cost limit).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    FallbackAgent,
    PhaseDefinition,
)

pytestmark = pytest.mark.unit

_FIXTURE = """
id: pc83-fallback-fixture
name: PC-83 fallback fixture
type: custom
classification: simple
phases:
  - id: verify
    name: Verify
    order: 1
    prompt_template: Verify the change.
    agent:
      provider: codex
      model: gpt-5-codex
    fallback_agent:
      provider: claude
      model: opus
"""


def _phase(**extra: object) -> PhaseYamlDefinition:
    return PhaseYamlDefinition.model_validate(
        {"id": "verify", "name": "Verify", "order": 1, "prompt_template": "x", **extra}
    )


def test_a_declared_fallback_reaches_the_stored_phase_definition() -> None:
    workflow = WorkflowDefinition.from_yaml(_FIXTURE)
    stored = workflow.phases[0].to_domain()

    # Through the serialisation WorkflowTemplateCreated stores phases in.
    replayed = PhaseDefinition.model_validate(stored.model_dump())

    assert replayed.fallback_agent == FallbackAgent(provider="claude", model="opus")
    assert replayed.provider == "codex"


def test_a_phase_without_a_fallback_stores_none() -> None:
    assert _phase().to_domain().fallback_agent is None


def test_a_codex_fallback_is_refused_on_a_phase_that_scopes_tools() -> None:
    with pytest.raises(ValidationError, match="cannot honour allowed_tools"):
        _phase(allowed_tools=["Read"], fallback_agent={"provider": "codex"})


def test_a_codex_fallback_is_refused_on_a_phase_with_a_cost_limit() -> None:
    with pytest.raises(ValidationError, match="max_cost_usd on provider 'codex'"):
        _phase(max_cost_usd=5.0, fallback_agent={"provider": "codex"})


def test_a_claude_fallback_keeps_the_phase_s_tools_and_limit() -> None:
    definition = _phase(
        allowed_tools=["Read"], max_cost_usd=5.0, fallback_agent={"provider": "claude"}
    ).to_domain()

    assert definition.fallback_agent == FallbackAgent(provider="claude", model=None)


@pytest.mark.parametrize(
    "fallback",
    [
        {},
        {"model": "opus"},
        {"provider": "claude-interactive"},
        {"provider": "claude", "sandbox": "workspace-write"},
    ],
)
def test_a_fallback_must_name_a_runnable_provider_and_nothing_else(
    fallback: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        _phase(fallback_agent=fallback)
