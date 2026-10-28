"""A command phase parses, and every field its kind does not apply is refused (ADR-078 D1, D2).

The refusal runs twice: at parse, and again at the execution boundary through
``require_consistent_phase_kind`` for a stored template. Both are driven here,
the second on a ``PhaseDefinition`` that never saw the YAML validator.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.command_phase import (
    CommandStep,
    InconsistentPhaseKindError,
    PhaseKind,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    require_consistent_phase_kind,
)

pytestmark = pytest.mark.unit

_WORKFLOW = """\
id: adr078-command-fixture
name: ADR-078 command fixture
type: custom
classification: simple
phases:
  - id: build
    name: Build probe
    order: 1
    kind: command
    timeout_seconds: 1800
    commands:
      - name: cargo-build
        run: cargo build --locked --release
        timeout_seconds: 900
      - name: report-only
        run: ./scripts/size-report.sh && echo done
        allow_failure: true
"""

_STEPS = [{"name": "build", "run": "make"}]


def _command_phase(**extra: object) -> PhaseYamlDefinition:
    return PhaseYamlDefinition.model_validate(
        {"id": "build", "name": "Build", "order": 1, "kind": "command", "commands": _STEPS, **extra}
    )


def test_a_command_phase_reaches_the_domain_with_its_steps_in_order() -> None:
    (phase,) = WorkflowDefinition.from_yaml(_WORKFLOW).get_domain_phases()

    assert phase.kind is PhaseKind.COMMAND
    assert phase.commands == (
        CommandStep(name="cargo-build", run="cargo build --locked --release", timeout_seconds=900),
        CommandStep(
            name="report-only", run="./scripts/size-report.sh && echo done", allow_failure=True
        ),
    )
    assert phase.timeout_seconds == 1800
    assert phase.prompt_template is None
    assert phase.model is None


def test_an_undeclared_kind_is_agent_so_every_existing_workflow_is_unchanged() -> None:
    phase = PhaseYamlDefinition.model_validate(
        {"id": "p", "name": "p", "order": 1, "prompt_template": "x"}
    )
    assert phase.to_domain().kind is PhaseKind.AGENT
    assert phase.to_domain().delivers_repo_changes is True


def test_a_command_phase_delivers_no_repo_changes_by_default() -> None:
    assert _command_phase().to_domain().delivers_repo_changes is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_template", "build it"),
        ("prompt_file", "phases/build.md"),
        ("model", "opus"),
        ("agent", {"provider": "claude"}),
        ("fallback_agent", {"provider": "claude"}),
        ("allowed_tools", ["Bash"]),
        ("max_cost_usd", 1.0),
        ("argument_hint", "[x]"),
        ("claude_plugins", ["owner/repo@abc123"]),
        ("skills", ["owner/repo/skill@abc123"]),
        ("requires_verdict", True),
        ("delivers_repo_changes", True),
        ("timeout_seconds", 0),
    ],
)
def test_a_field_the_command_kind_does_not_apply_is_refused_naming_the_phase(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError, match=r"Phase 'build' \(kind: command\)"):
        _command_phase(**{field: value})


def test_a_command_phase_with_no_steps_is_refused() -> None:
    with pytest.raises(ValidationError, match="'commands' is required"):
        _command_phase(commands=[])


def test_commands_on_an_agent_phase_are_refused() -> None:
    with pytest.raises(ValidationError, match="'commands' applies only to kind: command"):
        PhaseYamlDefinition.model_validate(
            {"id": "p", "name": "p", "order": 1, "prompt_template": "x", "commands": _STEPS}
        )


def test_two_steps_with_one_name_are_refused() -> None:
    with pytest.raises(ValidationError, match="'make' is used twice"):
        _command_phase(commands=[{"name": "make", "run": "a"}, {"name": "make", "run": "b"}])


@pytest.mark.parametrize("timeout", [0, -1, 1.5, "60"])
def test_a_step_timeout_is_a_positive_integer(timeout: object) -> None:
    with pytest.raises(ValidationError):
        CommandStep.model_validate({"name": "s", "run": "x", "timeout_seconds": timeout})


@pytest.mark.parametrize("name", ["Build", "-x", "a/b", "../log", "a" * 64, ""])
def test_a_step_name_is_a_file_name_safe_slug(name: str) -> None:
    with pytest.raises(ValidationError):
        CommandStep.model_validate({"name": name, "run": "x"})


def test_an_empty_run_is_refused() -> None:
    with pytest.raises(ValidationError):
        CommandStep.model_validate({"name": "s", "run": ""})


class TestTheExecutionBoundaryAppliesTheSameRule:
    """A stored template never sees the YAML validator (ADR-078 D2)."""

    _STEP = CommandStep(name="build", run="make")

    def test_a_stored_command_phase_carrying_a_prompt_is_refused(self) -> None:
        stored = PhaseDefinition(
            phase_id="build",
            name="Build",
            order=1,
            kind=PhaseKind.COMMAND,
            commands=(self._STEP,),
            prompt_template="smuggled in by a phase edit",
            delivers_repo_changes=False,
        )
        with pytest.raises(InconsistentPhaseKindError, match="prompt_template"):
            require_consistent_phase_kind(stored)

    def test_a_platform_defaulted_model_is_not_an_authored_one(self) -> None:
        stored = PhaseDefinition(
            phase_id="build",
            name="Build",
            order=1,
            kind=PhaseKind.COMMAND,
            commands=(self._STEP,),
            model="claude-opus-5-5",
            model_defaulted=True,
            delivers_repo_changes=False,
        )
        require_consistent_phase_kind(stored)

    def test_a_stored_agent_phase_is_untouched(self) -> None:
        require_consistent_phase_kind(
            PhaseDefinition(phase_id="p", name="p", order=1, prompt_template="x")
        )
