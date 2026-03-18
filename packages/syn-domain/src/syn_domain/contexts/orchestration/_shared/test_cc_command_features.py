"""Tests for ISS-211: Workflows as Claude Code Commands.

Tests $ARGUMENTS substitution, InputDeclaration, new PhaseDefinition fields,
YAML parsing with inputs section, and backward compatibility.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    WorkflowClassification,
    WorkflowType,
)


# =============================================================================
# InputDeclaration Tests
# =============================================================================


@pytest.mark.unit
class TestInputDeclaration:
    """Tests for InputDeclaration value object."""

    def test_basic_creation(self) -> None:
        decl = InputDeclaration(name="task", description="What to do", required=True)
        assert decl.name == "task"
        assert decl.description == "What to do"
        assert decl.required is True
        assert decl.default is None

    def test_with_default(self) -> None:
        decl = InputDeclaration(name="model", required=False, default="sonnet")
        assert decl.required is False
        assert decl.default == "sonnet"

    def test_immutable(self) -> None:
        from pydantic import ValidationError

        decl = InputDeclaration(name="task")
        with pytest.raises(ValidationError):
            decl.name = "changed"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        decl = InputDeclaration(name="task", description="desc", required=True, default="x")
        data = decl.model_dump()
        restored = InputDeclaration(**data)
        assert restored == decl


# =============================================================================
# PhaseDefinition Extension Tests
# =============================================================================


@pytest.mark.unit
class TestPhaseDefinitionExtensions:
    """Tests for new PhaseDefinition fields (argument_hint, model)."""

    def test_argument_hint(self) -> None:
        phase = PhaseDefinition(
            phase_id="p1",
            name="Test",
            order=1,
            argument_hint="[task-description]",
        )
        assert phase.argument_hint == "[task-description]"

    def test_model_override(self) -> None:
        phase = PhaseDefinition(
            phase_id="p1",
            name="Test",
            order=1,
            model="opus",
        )
        assert phase.model == "opus"

    def test_defaults_are_none(self) -> None:
        phase = PhaseDefinition(phase_id="p1", name="Test", order=1)
        assert phase.argument_hint is None
        assert phase.model is None

    def test_backward_compat_existing_fields_unchanged(self) -> None:
        """Existing fields still work when new fields are absent."""
        phase = PhaseDefinition(
            phase_id="p1",
            name="Test",
            order=1,
            prompt_template="Do something",
            max_tokens=4096,
        )
        assert phase.prompt_template == "Do something"
        assert phase.max_tokens == 4096


# =============================================================================
# YAML Parsing Tests
# =============================================================================


YAML_WITH_INPUTS = """
id: test-cc-workflow
name: CC Command Workflow
type: research
classification: standard

inputs:
  - name: task
    description: "What to research"
    required: true
  - name: topic
    description: "Short topic label"
    required: false
    default: "general"

phases:
  - id: discovery
    name: Discovery
    order: 1
    argument_hint: "[task-description]"
    model: sonnet
    prompt_template: |
      Research this:
      $ARGUMENTS

      Topic: {{topic}}
"""

YAML_WITHOUT_INPUTS = """
id: legacy-workflow
name: Legacy Workflow
phases:
  - id: p1
    name: Phase 1
    order: 1
    prompt_template: "{{topic}}"
"""


@pytest.mark.unit
class TestYamlWithInputs:
    """Tests for YAML parsing with inputs section."""

    def test_parse_inputs(self) -> None:
        defn = WorkflowDefinition.from_yaml(YAML_WITH_INPUTS)
        assert len(defn.inputs) == 2
        assert defn.inputs[0].name == "task"
        assert defn.inputs[0].required is True
        assert defn.inputs[1].name == "topic"
        assert defn.inputs[1].default == "general"

    def test_domain_input_declarations(self) -> None:
        defn = WorkflowDefinition.from_yaml(YAML_WITH_INPUTS)
        decls = defn.get_domain_input_declarations()
        assert len(decls) == 2
        assert isinstance(decls[0], InputDeclaration)
        assert decls[0].name == "task"

    def test_phase_argument_hint(self) -> None:
        defn = WorkflowDefinition.from_yaml(YAML_WITH_INPUTS)
        phase = defn.phases[0]
        assert phase.argument_hint == "[task-description]"

    def test_phase_model(self) -> None:
        defn = WorkflowDefinition.from_yaml(YAML_WITH_INPUTS)
        phase = defn.phases[0]
        assert phase.model == "sonnet"

    def test_domain_phase_carries_new_fields(self) -> None:
        defn = WorkflowDefinition.from_yaml(YAML_WITH_INPUTS)
        domain_phases = defn.get_domain_phases()
        assert domain_phases[0].argument_hint == "[task-description]"
        assert domain_phases[0].model == "sonnet"

    def test_backward_compat_no_inputs(self) -> None:
        """YAML without inputs section still parses fine."""
        defn = WorkflowDefinition.from_yaml(YAML_WITHOUT_INPUTS)
        assert defn.inputs == []
        assert defn.get_domain_input_declarations() == []

    def test_backward_compat_no_argument_hint(self) -> None:
        """Phases without argument_hint still work."""
        defn = WorkflowDefinition.from_yaml(YAML_WITHOUT_INPUTS)
        phase = defn.phases[0]
        assert phase.argument_hint is None
        assert phase.model is None


# =============================================================================
# $ARGUMENTS Substitution Tests
# =============================================================================


@pytest.mark.unit
class TestArgumentsSubstitution:
    """Tests for $ARGUMENTS substitution logic.

    The actual substitution happens in _build_workspace_prompt in _wiring.py.
    These tests verify the logic in isolation.
    """

    @staticmethod
    def _substitute(template: str, task: str, inputs: dict[str, str] | None = None) -> str:
        """Simulate the substitution logic from _build_workspace_prompt."""
        result = template
        if inputs:
            for key, value in inputs.items():
                result = result.replace(f"{{{{{key}}}}}", value)
        result = result.replace("$ARGUMENTS", str((inputs or {}).get("task", task)))
        return result

    def test_basic_substitution(self) -> None:
        template = "Do this: $ARGUMENTS"
        result = self._substitute(template, "fix the bug")
        assert result == "Do this: fix the bug"

    def test_arguments_and_variables_coexist(self) -> None:
        template = "$ARGUMENTS\n\nTopic: {{topic}}"
        result = self._substitute(template, "research AI", {"topic": "AI Agents"})
        assert "AI Agents" in result
        assert "research AI" in result

    def test_missing_task_empty_string(self) -> None:
        template = "Task: $ARGUMENTS"
        result = self._substitute(template, "")
        assert result == "Task: "

    def test_legacy_variables_only(self) -> None:
        """Templates with only {{variable}} still work."""
        template = "Topic: {{topic}}"
        result = self._substitute(template, "", {"topic": "AI"})
        assert result == "Topic: AI"

    def test_no_substitution_markers(self) -> None:
        """Templates with no markers are unchanged."""
        template = "Just a plain prompt"
        result = self._substitute(template, "anything")
        assert result == "Just a plain prompt"


# =============================================================================
# Aggregate + Event Round-Trip Tests
# =============================================================================


@pytest.mark.unit
class TestAggregateInputDeclarations:
    """Tests for input_declarations flowing through aggregate creation."""

    def test_create_with_input_declarations(self) -> None:
        aggregate = WorkflowTemplateAggregate()
        command = CreateWorkflowTemplateCommand(
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            phases=[PhaseDefinition(phase_id="p1", name="Phase 1", order=1)],
            input_declarations=[
                InputDeclaration(name="task", description="What to do", required=True),
            ],
        )
        aggregate._handle_command(command)

        assert len(aggregate.input_declarations) == 1
        assert aggregate.input_declarations[0].name == "task"

    def test_create_without_input_declarations(self) -> None:
        """Backward compat: no input_declarations defaults to empty list."""
        aggregate = WorkflowTemplateAggregate()
        command = CreateWorkflowTemplateCommand(
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            phases=[PhaseDefinition(phase_id="p1", name="Phase 1", order=1)],
        )
        aggregate._handle_command(command)

        assert aggregate.input_declarations == []

    def test_event_carries_input_declarations(self) -> None:
        aggregate = WorkflowTemplateAggregate()
        command = CreateWorkflowTemplateCommand(
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            phases=[PhaseDefinition(phase_id="p1", name="Phase 1", order=1)],
            input_declarations=[
                InputDeclaration(name="task", required=True),
                InputDeclaration(name="repo", required=False, default="main"),
            ],
        )
        aggregate._handle_command(command)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        event = events[0].event
        assert len(event.input_declarations) == 2
        assert event.input_declarations[0].name == "task"


# =============================================================================
# Example YAML Validation Tests
# =============================================================================


@pytest.mark.unit
class TestExampleWorkflows:
    """Verify updated example workflows parse correctly."""

    @pytest.fixture
    def examples_dir(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parents[7] / "workflows" / "examples")

    def test_research_yaml_parses(self, examples_dir: str) -> None:
        from pathlib import Path

        defn = WorkflowDefinition.from_file(Path(examples_dir) / "research.yaml")
        assert defn.id == "research-workflow-v2"
        assert len(defn.inputs) >= 1
        task_input = next(i for i in defn.inputs if i.name == "task")
        assert task_input.required is True
        # Verify $ARGUMENTS in prompts
        assert "$ARGUMENTS" in (defn.phases[0].prompt_template or "")

    def test_implementation_yaml_parses(self, examples_dir: str) -> None:
        from pathlib import Path

        defn = WorkflowDefinition.from_file(Path(examples_dir) / "implementation.yaml")
        assert defn.id == "implementation-workflow-v1"
        assert len(defn.inputs) >= 1

    def test_github_pr_yaml_parses(self, examples_dir: str) -> None:
        from pathlib import Path

        defn = WorkflowDefinition.from_file(Path(examples_dir) / "github-pr.yaml")
        assert defn.id == "github-pr-workflow"
        assert len(defn.inputs) >= 1
        # Verify both $ARGUMENTS and {{variable}} coexist
        create_pr_phase = defn.phases[0]
        assert "$ARGUMENTS" in (create_pr_phase.prompt_template or "")
        assert "{{repo_url}}" in (create_pr_phase.prompt_template or "")
