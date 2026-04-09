"""Tests for workflow YAML definition parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    load_workflow_definitions,
    validate_workflow_yaml,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseExecutionType,
    WorkflowClassification,
)

VALID_WORKFLOW_YAML = """
id: test-workflow-v1
name: Test Workflow
description: A test workflow

type: research
classification: standard

repository:
  url: https://github.com/test/repo
  ref: main

phases:
  - id: phase-1
    name: First Phase
    order: 1
    execution_type: sequential
    description: First phase description
    input_artifacts: []
    output_artifacts:
      - output_1
    max_tokens: 4096
    timeout_seconds: 300

  - id: phase-2
    name: Second Phase
    order: 2
    execution_type: human_in_loop
    input_artifacts:
      - output_1
    output_artifacts:
      - final_output
"""


@pytest.mark.unit
def test_parse_valid_workflow_yaml() -> None:
    """Test parsing a valid workflow YAML."""
    definition = WorkflowDefinition.from_yaml(VALID_WORKFLOW_YAML)

    assert definition.id == "test-workflow-v1"
    assert definition.name == "Test Workflow"
    assert definition.description == "A test workflow"
    assert definition.type == "research"
    assert definition.classification == WorkflowClassification.STANDARD
    assert definition.repository is not None
    assert definition.repository.url == "https://github.com/test/repo"
    assert definition.repository.ref == "main"
    assert len(definition.phases) == 2


def test_parse_phases() -> None:
    """Test parsing phase definitions."""
    definition = WorkflowDefinition.from_yaml(VALID_WORKFLOW_YAML)

    phase1 = definition.phases[0]
    assert phase1.id == "phase-1"
    assert phase1.name == "First Phase"
    assert phase1.order == 1
    assert phase1.execution_type == PhaseExecutionType.SEQUENTIAL
    assert phase1.output_artifacts == ["output_1"]
    assert phase1.max_tokens == 4096

    phase2 = definition.phases[1]
    assert phase2.execution_type == PhaseExecutionType.HUMAN_IN_LOOP
    assert phase2.input_artifacts == ["output_1"]


def test_convert_phases_to_domain() -> None:
    """Test converting phases to domain PhaseDefinition objects."""
    definition = WorkflowDefinition.from_yaml(VALID_WORKFLOW_YAML)
    domain_phases = definition.get_domain_phases()

    assert len(domain_phases) == 2
    assert domain_phases[0].phase_id == "phase-1"
    assert domain_phases[0].input_artifact_types == []
    assert domain_phases[0].output_artifact_types == ["output_1"]


def test_validate_workflow_yaml_valid() -> None:
    """Test validation of valid workflow YAML."""
    is_valid, error = validate_workflow_yaml(VALID_WORKFLOW_YAML)
    assert is_valid is True
    assert error is None


def test_validate_workflow_yaml_invalid() -> None:
    """Test validation of invalid workflow YAML."""
    invalid_yaml = """
    id: test
    name: Test
    # Missing required phases
    """
    is_valid, error = validate_workflow_yaml(invalid_yaml)
    assert is_valid is False
    assert error is not None


def test_parse_minimal_workflow() -> None:
    """Test parsing a minimal valid workflow."""
    minimal_yaml = """
    id: minimal
    name: Minimal Workflow
    phases:
      - id: p1
        name: Phase 1
        order: 1
    """
    definition = WorkflowDefinition.from_yaml(minimal_yaml)
    assert definition.id == "minimal"
    assert definition.type == "custom"  # Default
    assert definition.classification == WorkflowClassification.STANDARD  # Default


def test_duplicate_phase_ids_rejected() -> None:
    """Test that duplicate phase IDs are rejected."""
    invalid_yaml = """
    id: test
    name: Test
    phases:
      - id: same-id
        name: Phase 1
        order: 1
      - id: same-id
        name: Phase 2
        order: 2
    """
    with pytest.raises(ValueError, match="Phase IDs must be unique"):
        WorkflowDefinition.from_yaml(invalid_yaml)


def test_duplicate_phase_orders_rejected() -> None:
    """Test that duplicate phase orders are rejected."""
    invalid_yaml = """
    id: test
    name: Test
    phases:
      - id: p1
        name: Phase 1
        order: 1
      - id: p2
        name: Phase 2
        order: 1
    """
    with pytest.raises(ValueError, match="Phase orders must be unique"):
        WorkflowDefinition.from_yaml(invalid_yaml)


def test_load_from_file() -> None:
    """Test loading workflow from a file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(VALID_WORKFLOW_YAML)
        f.flush()
        path = Path(f.name)

    try:
        definition = WorkflowDefinition.from_file(path)
        assert definition.id == "test-workflow-v1"
    finally:
        path.unlink()


def test_load_workflow_definitions_from_directory() -> None:
    """Test loading multiple workflows from a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        # Create two workflow files
        (dir_path / "workflow1.yaml").write_text("""
id: workflow-1
name: Workflow 1
phases:
  - id: p1
    name: Phase 1
    order: 1
""")
        (dir_path / "workflow2.yml").write_text("""
id: workflow-2
name: Workflow 2
phases:
  - id: p1
    name: Phase 1
    order: 1
""")

        definitions = load_workflow_definitions(dir_path)
        assert len(definitions) == 2
        ids = {d.id for d in definitions}
        assert ids == {"workflow-1", "workflow-2"}


def test_load_from_nonexistent_directory() -> None:
    """Test loading from a non-existent directory raises error."""
    with pytest.raises(FileNotFoundError):
        load_workflow_definitions(Path("/nonexistent/path"))


# =============================================================================
# prompt_file Tests (ISS-398)
# =============================================================================


def test_load_from_file_with_prompt_file() -> None:
    """End-to-end: YAML with prompt_file resolves .md content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        # Create the .md prompt file.
        prompts = dir_path / "prompts"
        prompts.mkdir()
        (prompts / "research.md").write_text(
            "---\nmodel: sonnet\nmax-tokens: 4096\n---\n\n"
            "You are a research assistant.\n\n"
            "## Task\n$ARGUMENTS\n"
        )

        # Create the YAML workflow referencing it.
        yaml_file = dir_path / "workflow.yaml"
        yaml_file.write_text(
            "id: prompt-file-wf\n"
            "name: Prompt File Workflow\n"
            "phases:\n"
            "  - id: research\n"
            "    name: Research\n"
            "    order: 1\n"
            "    prompt_file: prompts/research.md\n"
        )

        defn = WorkflowDefinition.from_file(yaml_file)
        assert defn.id == "prompt-file-wf"

        phase = defn.phases[0]
        assert phase.prompt_template is not None
        assert "research assistant" in phase.prompt_template
        assert "$ARGUMENTS" in phase.prompt_template
        assert phase.model == "sonnet"
        assert phase.max_tokens == 4096
        assert phase.prompt_file is None  # resolved away

        # Domain conversion should also work.
        domain_phases = defn.get_domain_phases()
        assert domain_phases[0].prompt_template is not None
        assert domain_phases[0].model == "sonnet"


def test_load_workflow_definitions_with_prompt_files() -> None:
    """Directory with mixed inline and .md-referenced workflows all load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        # Workflow 1: inline prompt_template.
        (dir_path / "inline.yaml").write_text(
            "id: inline-wf\n"
            "name: Inline\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            '    prompt_template: "Inline prompt."\n'
        )

        # Workflow 2: prompt_file reference.
        (dir_path / "phase.md").write_text("External prompt content.")
        (dir_path / "external.yaml").write_text(
            "id: external-wf\n"
            "name: External\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: Phase 1\n"
            "    order: 1\n"
            "    prompt_file: phase.md\n"
        )

        definitions = load_workflow_definitions(dir_path)
        assert len(definitions) == 2
        ids = {d.id for d in definitions}
        assert ids == {"inline-wf", "external-wf"}

        # Verify both have resolved prompts.
        for defn in definitions:
            domain_phases = defn.get_domain_phases()
            assert domain_phases[0].prompt_template is not None


# =============================================================================
# Root Type Guard Tests (Fix 3, Fix 4)
# =============================================================================


def test_from_file_empty_yaml(tmp_path: Path) -> None:
    """Empty YAML file raises ValueError about root mapping."""
    yaml_file = tmp_path / "workflow.yaml"
    yaml_file.write_text("")

    with pytest.raises(ValueError, match="must be a mapping"):
        WorkflowDefinition.from_file(yaml_file)


def test_from_file_list_yaml(tmp_path: Path) -> None:
    """YAML list at root raises ValueError about root mapping."""
    yaml_file = tmp_path / "workflow.yaml"
    yaml_file.write_text("- item1\n- item2\n")

    with pytest.raises(ValueError, match="must be a mapping"):
        WorkflowDefinition.from_file(yaml_file)


def test_validate_empty_yaml_with_base_dir(tmp_path: Path) -> None:
    """validate_workflow_yaml with empty content and base_dir returns error."""
    is_valid, error = validate_workflow_yaml("", base_dir=tmp_path)
    assert is_valid is False
    assert error is not None
    assert "must be a mapping" in error
