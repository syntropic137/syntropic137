"""A sandbox level the workspace cannot run is refused before anything is paid for (#1434).

Codex enforces every level below full-access with bubblewrap, which cannot
create a namespace in the workspace container: a ``read-only`` or
``workspace-write`` phase failed on its first command, after earlier phases
had already run. Claude ignores the field, so the level would be a promise
nobody keeps. Refused at authoring AND at the execution boundary, because a
stored template never sees the YAML validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    validate_phase_declarations,
)
from syn_shared.agents import UnrunnablePhaseSandboxError

pytestmark = pytest.mark.unit

UNRUNNABLE = ("read-only",)


@dataclass(frozen=True)
class _StoredPhase:
    """The attributes `validate_phase_declarations` reads from a stored phase."""

    phase_id: str
    sandbox: str
    provider: str = "codex"
    execution_type: str = "sequential"
    allowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class _StoredTemplate:
    phases: list[_StoredPhase] = field(default_factory=list)


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
    with pytest.raises(ValidationError, match=r"artifacts/output.*#1434"):
        WorkflowDefinition.from_yaml(_yaml(provider, sandbox))


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize(
    ("sandbox", "expected"),
    [(None, "full-access"), ("full-access", "full-access"), ("workspace-write", "workspace-write")],
)
def test_authoring_accepts_the_runnable_level(
    provider: str, sandbox: str | None, expected: str
) -> None:
    definition = WorkflowDefinition.from_yaml(_yaml(provider, sandbox))
    assert definition.phases[0].to_domain().sandbox == expected


@pytest.mark.parametrize("sandbox", UNRUNNABLE)
def test_a_stored_template_is_refused_at_the_execution_boundary(sandbox: str) -> None:
    stored = _StoredTemplate(phases=[_StoredPhase(phase_id="review", sandbox=sandbox)])
    with pytest.raises(UnrunnablePhaseSandboxError, match="review"):
        validate_phase_declarations(cast("object", stored))  # type: ignore[arg-type]


@dataclass(frozen=True)
class _RehydratedTemplate:
    """What `_get_executable_phases` reads: real `PhaseDefinition`s, as replay builds them."""

    phases: list[object]
    claude_plugins: tuple[object, ...] = ()
    skills: tuple[object, ...] = ()


@pytest.mark.parametrize("sandbox", UNRUNNABLE)
async def test_a_direct_handler_caller_is_refused_before_provisioning(sandbox: str) -> None:
    """`handle()` does not call validate_phase_declarations; its own loop must refuse."""
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

    # Replay constructs PhaseDefinition with no YAML validator in the way.
    phase = PhaseDefinition(phase_id="review", name="Review", order=1, sandbox=sandbox)
    handler = ExecuteWorkflowHandler.__new__(ExecuteWorkflowHandler)
    with pytest.raises(UnrunnablePhaseSandboxError, match="review"):
        await handler._get_executable_phases(
            cast("object", _RehydratedTemplate(phases=[phase]))  # type: ignore[arg-type]
        )
