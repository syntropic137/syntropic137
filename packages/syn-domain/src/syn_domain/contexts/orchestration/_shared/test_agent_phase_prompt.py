"""An agent phase without a prompt is refused; a command phase needs none (#963).

Before this rule a phase that left both ``prompt_template`` and ``prompt_file``
unset was dispatched with an empty prompt and billed (#961). The refusal is driven at each place a phase enters: the YAML at
parse, ``from_file`` at install, and the execution boundary for a template
stored before the rule existed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.command_phase import (
    CommandStep,
    InconsistentPhaseKindError,
    PhaseKind,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    validate_phase_declarations,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_HEADER = """\
id: prompt-fixture
name: Prompt fixture
type: custom
classification: simple
phases:
"""


def _workflow(phase: str) -> str:
    return _HEADER + phase


class _Template:
    """The two attributes ``validate_phase_declarations`` reads off a stored template."""

    def __init__(self, *phases: PhaseDefinition) -> None:
        self.phases = list(phases)
        self.skills = ()


def test_an_agent_phase_with_no_prompt_is_refused_naming_the_phase() -> None:
    yaml = _workflow("  - id: implement-fix\n    name: Implement\n    order: 1\n")
    with pytest.raises(ValidationError) as exc:
        WorkflowDefinition.from_yaml(yaml)
    message = str(exc.value)
    assert "Phase 'implement-fix' (kind: agent)" in message
    assert "needs 'prompt_template' or 'prompt_file'" in message


def test_a_blank_prompt_template_is_no_prompt() -> None:
    yaml = _workflow("  - id: blank\n    name: Blank\n    order: 1\n    prompt_template: '  '\n")
    with pytest.raises(ValidationError, match="Phase 'blank'"):
        WorkflowDefinition.from_yaml(yaml)


def test_a_command_phase_with_no_prompt_is_accepted() -> None:
    yaml = _workflow(
        """\
  - id: build
    name: Build
    order: 1
    kind: command
    commands:
      - name: build
        run: make
"""
    )
    (phase,) = WorkflowDefinition.from_yaml(yaml).get_domain_phases()
    assert phase.kind is PhaseKind.COMMAND
    assert phase.prompt_template is None


def test_an_agent_phase_with_a_prompt_template_is_accepted() -> None:
    yaml = _workflow("  - id: p\n    name: P\n    order: 1\n    prompt_template: Do the thing.\n")
    (phase,) = WorkflowDefinition.from_yaml(yaml).get_domain_phases()
    assert phase.prompt_template == "Do the thing."


def test_an_agent_phase_with_only_a_prompt_file_is_accepted_at_install(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_text("Prompt from a file.")
    path = tmp_path / "workflow.yaml"
    path.write_text(_workflow("  - id: p\n    name: P\n    order: 1\n    prompt_file: p.md\n"))

    (phase,) = WorkflowDefinition.from_file(path).get_domain_phases()
    assert phase.prompt_template == "Prompt from a file."


def test_an_empty_prompt_file_is_no_prompt_at_install(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_text("")
    path = tmp_path / "workflow.yaml"
    path.write_text(
        _workflow("  - id: empty-file\n    name: P\n    order: 1\n    prompt_file: p.md\n")
    )

    with pytest.raises(ValidationError, match="Phase 'empty-file' \\(kind: agent\\)"):
        WorkflowDefinition.from_file(path)


def test_an_unresolved_prompt_file_still_parses_under_from_yaml() -> None:
    # from_yaml cannot read files; the prompt exists, the domain cannot see it yet.
    yaml = _workflow("  - id: p\n    name: P\n    order: 1\n    prompt_file: p.md\n")
    definition = WorkflowDefinition.from_yaml(yaml)
    assert definition.phases[0].prompt_file == "p.md"


def test_a_stored_agent_phase_with_no_prompt_is_refused_at_execution() -> None:
    # A template stored before #963 never passes the YAML validator again.
    stored = _Template(PhaseDefinition(phase_id="legacy", name="Legacy", order=1))
    with pytest.raises(InconsistentPhaseKindError, match="Phase 'legacy' \\(kind: agent\\)"):
        validate_phase_declarations(stored)  # type: ignore[arg-type]


def test_a_stored_command_phase_with_no_prompt_passes_execution() -> None:
    stored = _Template(
        PhaseDefinition(
            phase_id="build",
            name="Build",
            order=1,
            kind=PhaseKind.COMMAND,
            commands=(CommandStep(name="build", run="make"),),
            delivers_repo_changes=False,
        )
    )
    validate_phase_declarations(stored)  # type: ignore[arg-type]
