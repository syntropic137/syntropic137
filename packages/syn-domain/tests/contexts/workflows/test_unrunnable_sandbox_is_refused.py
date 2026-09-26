"""A sandbox level the workspace cannot run is refused before anything is paid for (#1434).

Codex enforces every level below full-access with bubblewrap, which cannot
create a namespace in the workspace container: a ``read-only`` or
``workspace-write`` phase failed on its first command, after earlier phases
had already run. Claude ignores the field, so the level would be a promise
nobody keeps. Refused at authoring AND at the execution boundary, because a
stored template never sees the YAML validator.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    validate_phase_declarations,
)
from syn_shared.agents import UnrunnablePhaseSandboxError

pytestmark = pytest.mark.unit

UNRUNNABLE = ("read-only", "workspace-write")


def _yaml(provider: str, sandbox: str | None) -> str:
    line = f"\n      sandbox: {sandbox}" if sandbox else ""
    return f"""
id: sandbox-refusal
name: sandbox-refusal
description: d
phases:
  - id: review
    name: Review
    order: 1
    prompt_template: check the work
    agent:
      provider: {provider}{line}
"""


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("sandbox", UNRUNNABLE)
def test_authoring_refuses_an_unrunnable_level(provider: str, sandbox: str) -> None:
    with pytest.raises(ValidationError, match=r"cannot run in the workspace container.*#1434"):
        WorkflowDefinition.from_yaml(_yaml(provider, sandbox))


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("sandbox", [None, "full-access"])
def test_authoring_accepts_the_runnable_level(provider: str, sandbox: str | None) -> None:
    definition = WorkflowDefinition.from_yaml(_yaml(provider, sandbox))
    assert definition.phases[0].to_domain().sandbox == "full-access"


@pytest.mark.parametrize("sandbox", UNRUNNABLE)
def test_a_stored_template_is_refused_at_the_execution_boundary(sandbox: str) -> None:
    stored = SimpleNamespace(
        phases=[
            SimpleNamespace(
                phase_id="review",
                execution_type="sequential",
                allowed_tools=(),
                provider="codex",
                sandbox=sandbox,
            )
        ]
    )
    with pytest.raises(UnrunnablePhaseSandboxError, match="review"):
        validate_phase_declarations(cast("object", stored))  # type: ignore[arg-type]
