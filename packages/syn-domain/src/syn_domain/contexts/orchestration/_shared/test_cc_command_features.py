"""Tests for ISS-211: Workflows as Claude Code Commands.

Tests $ARGUMENTS substitution, InputDeclaration, new PhaseDefinition fields,
YAML parsing with inputs section, backward compatibility, and prompt_file (ISS-398).
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - needed at runtime

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
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

    def test_defaults_applied_to_merged_inputs(self) -> None:
        """Input declaration defaults are applied when inputs are missing."""
        aggregate = WorkflowTemplateAggregate()
        command = CreateWorkflowTemplateCommand(
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            phases=[PhaseDefinition(phase_id="p1", name="Phase 1", order=1)],
            input_declarations=[
                InputDeclaration(name="repository", default="https://github.com/default/repo"),
                InputDeclaration(name="task", required=True),
            ],
        )
        aggregate._handle_command(command)

        # Verify defaults are stored
        decls = aggregate.input_declarations
        repo_decl = next(d for d in decls if d.name == "repository")
        assert repo_decl.default == "https://github.com/default/repo"

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


# =============================================================================
# Prompt File Tests (ISS-398)
# =============================================================================


@pytest.mark.unit
class TestPromptFile:
    """Tests for prompt_file resolution and frontmatter merge."""

    def test_prompt_file_resolves_from_file(self, tmp_path: Path) -> None:
        """YAML with prompt_file resolves .md content into prompt_template."""
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "discovery.md").write_text(
            "---\nmodel: sonnet\n---\n\nYou are a research assistant.\n"
        )
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: discovery\n"
            "    name: Discovery\n"
            "    order: 1\n"
            "    prompt_file: prompts/discovery.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file)
        phase = defn.phases[0]
        assert phase.prompt_template == "You are a research assistant."
        assert phase.prompt_file is None  # resolved away
        assert phase.model == "sonnet"

    def test_prompt_file_and_template_mutual_exclusion(self) -> None:
        """Cannot set both prompt_template and prompt_file."""
        yaml_content = """
id: test-wf
name: Test
phases:
  - id: p1
    name: Phase 1
    order: 1
    prompt_template: "inline prompt"
    prompt_file: prompts/phase.md
"""
        with pytest.raises(ValueError, match="specify either 'prompt_template' or 'prompt_file'"):
            WorkflowDefinition.from_yaml(yaml_content)

    def test_frontmatter_merges_into_phase(self, tmp_path: Path) -> None:
        """.md frontmatter values populate phase fields when YAML doesn't set them."""
        (tmp_path / "phase.md").write_text(
            "---\n"
            "model: opus\n"
            "argument-hint: '[task]'\n"
            "max-tokens: 8192\n"
            "timeout-seconds: 600\n"
            "allowed-tools: Read, Grep\n"
            "---\n\n"
            "Do the work.\n"
        )
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: phase.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file)
        phase = defn.phases[0]
        assert phase.model == "opus"
        assert phase.argument_hint == "[task]"
        assert phase.max_tokens == 8192
        assert phase.timeout_seconds == 600
        assert phase.allowed_tools == ["Read", "Grep"]

    def test_yaml_overrides_frontmatter(self, tmp_path: Path) -> None:
        """YAML phase config takes precedence over .md frontmatter."""
        (tmp_path / "phase.md").write_text(
            "---\nmodel: opus\nmax-tokens: 8192\n---\n\nPrompt body.\n"
        )
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    model: sonnet\n"
            "    prompt_file: phase.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file)
        phase = defn.phases[0]
        assert phase.model == "sonnet"  # YAML wins
        assert phase.max_tokens == 8192  # frontmatter fills gap

    def test_allowed_tools_from_frontmatter(self, tmp_path: Path) -> None:
        """.md allowed-tools flows to domain PhaseDefinition."""
        (tmp_path / "phase.md").write_text(
            "---\nallowed-tools: Bash, Read, Grep\n---\n\nDo work.\n"
        )
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: phase.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file)
        domain_phases = defn.get_domain_phases()
        assert domain_phases[0].allowed_tools == ["Bash", "Read", "Grep"]

    def test_allowed_tools_from_yaml(self) -> None:
        """allowed_tools in YAML flows to domain PhaseDefinition."""
        yaml_content = """
id: test-wf
name: Test
phases:
  - id: p1
    name: Phase 1
    order: 1
    allowed_tools:
      - Bash
      - Read
    prompt_template: "Do work."
"""
        defn = WorkflowDefinition.from_yaml(yaml_content)
        domain_phases = defn.get_domain_phases()
        assert domain_phases[0].allowed_tools == ["Bash", "Read"]

    def test_missing_md_file_error(self, tmp_path: Path) -> None:
        """Referencing a non-existent .md file raises FileNotFoundError."""
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: nonexistent.md\n"
        )

        with pytest.raises(FileNotFoundError, match=r"nonexistent\.md"):
            WorkflowDefinition.from_file(yaml_file)

    def test_prompt_file_unresolved_guard(self) -> None:
        """to_domain() raises if prompt_file was not resolved."""
        yaml_content = """
id: test-wf
name: Test
phases:
  - id: p1
    name: Phase 1
    order: 1
    prompt_file: prompts/phase.md
"""
        defn = WorkflowDefinition.from_yaml(yaml_content)
        with pytest.raises(ValueError, match="was not resolved"):
            defn.get_domain_phases()

    def test_backward_compat_inline_prompt_unchanged(self) -> None:
        """Existing inline prompt_template workflows still parse correctly."""
        yaml_content = """
id: legacy-wf
name: Legacy
phases:
  - id: p1
    name: Phase 1
    order: 1
    prompt_template: "Do the thing."
    max_tokens: 4096
"""
        defn = WorkflowDefinition.from_yaml(yaml_content)
        phase = defn.phases[0]
        assert phase.prompt_template == "Do the thing."
        assert phase.prompt_file is None
        domain_phases = defn.get_domain_phases()
        assert domain_phases[0].prompt_template == "Do the thing."

    def test_prompt_file_with_arguments_substitution(self, tmp_path: Path) -> None:
        """$ARGUMENTS in .md content is preserved for runtime substitution."""
        (tmp_path / "phase.md").write_text(
            "---\nmodel: sonnet\n---\n\n## Your Task\n$ARGUMENTS\n\n## Context\n{{topic}}\n"
        )
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: phase.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file)
        assert "$ARGUMENTS" in (defn.phases[0].prompt_template or "")
        assert "{{topic}}" in (defn.phases[0].prompt_template or "")

    def test_custom_base_dir(self, tmp_path: Path) -> None:
        """prompt_file resolves relative to explicit base_dir."""
        prompts_dir = tmp_path / "shared_prompts"
        prompts_dir.mkdir()
        (prompts_dir / "phase.md").write_text("Research prompt content.")

        yaml_dir = tmp_path / "workflows"
        yaml_dir.mkdir()
        yaml_file = yaml_dir / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: phase.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file, base_dir=prompts_dir)
        assert defn.phases[0].prompt_template == "Research prompt content."

    def test_both_prompt_template_and_file_in_yaml_from_file(self, tmp_path: Path) -> None:
        """from_file() rejects YAML that has both prompt_template and prompt_file."""
        (tmp_path / "phase.md").write_text("External prompt.")
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            '    prompt_template: "inline prompt"\n'
            "    prompt_file: phase.md\n"
        )

        with pytest.raises(ValueError, match="specify either 'prompt_template' or 'prompt_file'"):
            WorkflowDefinition.from_file(yaml_file)

    def test_prompt_file_absolute_path_rejected(self, tmp_path: Path) -> None:
        """Absolute paths in prompt_file are rejected."""
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: /etc/passwd\n"
        )

        with pytest.raises(ValueError, match="must be a relative path"):
            WorkflowDefinition.from_file(yaml_file)

    def test_prompt_file_traversal_rejected(self, tmp_path: Path) -> None:
        """Path traversal via ../ in prompt_file is rejected."""
        yaml_file = tmp_path / "workflow.yaml"
        yaml_file.write_text(
            "id: test-wf\n"
            "name: Test\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: ../../etc/passwd\n"
        )

        with pytest.raises(ValueError, match="escapes base directory"):
            WorkflowDefinition.from_file(yaml_file)
