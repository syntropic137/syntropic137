"""Tests for workflow YAML definition parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

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


# =============================================================================
# Per-phase agent block Tests (interactive-tmux integration, PR #765)
# =============================================================================

AGENT_BLOCK_WORKFLOW_YAML = """
id: agent-block-wf
name: Agent Block Workflow
requires_repos: false

phases:
  - id: interactive
    name: Interactive Phase
    order: 1
    agent:
      provider: claude-interactive
      agent_id: codex
      model: sonnet
    prompt_template: Reply with OK.

  - id: standard
    name: Standard Phase
    order: 2
    prompt_template: Summarize the result.
"""


def test_parse_agent_block() -> None:
    """agent.provider / agent.model are parsed from the YAML phase."""
    definition = WorkflowDefinition.from_yaml(AGENT_BLOCK_WORKFLOW_YAML)

    interactive = definition.phases[0]
    assert interactive.agent is not None
    assert interactive.agent.provider == "claude-interactive"
    assert interactive.agent.agent_id == "codex"
    assert interactive.agent.model == "sonnet"

    standard = definition.phases[1]
    assert standard.agent is None


def test_agent_block_reaches_domain_phase() -> None:
    """to_domain() threads agent.provider and agent.model fallback through."""
    definition = WorkflowDefinition.from_yaml(AGENT_BLOCK_WORKFLOW_YAML)
    domain_phases = definition.get_domain_phases()

    assert domain_phases[0].provider == "claude-interactive"
    assert domain_phases[0].agent_id == "codex"
    assert domain_phases[0].model == "sonnet"  # agent.model fallback

    assert domain_phases[1].provider is None
    assert domain_phases[1].agent_id is None
    assert domain_phases[1].model is None


def test_top_level_model_wins_over_agent_model() -> None:
    """Top-level phase model takes precedence over agent.model."""
    yaml_content = """
id: model-precedence-wf
name: Model Precedence Workflow
requires_repos: false

phases:
  - id: p1
    name: Phase 1
    order: 1
    model: opus
    agent:
      provider: claude-interactive
      model: sonnet
    prompt_template: Do the thing.
"""
    definition = WorkflowDefinition.from_yaml(yaml_content)
    domain_phase = definition.get_domain_phases()[0]
    assert domain_phase.model == "opus"
    assert domain_phase.provider == "claude-interactive"


@pytest.mark.anyio
async def test_agent_provider_reaches_executable_phase() -> None:
    """agent.provider flows into ExecutablePhase.agent_config.provider."""
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

    definition = WorkflowDefinition.from_yaml(AGENT_BLOCK_WORKFLOW_YAML)

    class _StubTemplate:
        phases = definition.get_domain_phases()
        claude_plugins = ()
        skills = ()

    handler = ExecuteWorkflowHandler(
        processor=MagicMock(),
        workflow_repository=MagicMock(),
    )
    executable = await handler._get_executable_phases(_StubTemplate())  # type: ignore[arg-type]

    assert executable[0].agent_config.provider == "claude-interactive"
    assert executable[0].agent_config.agent_id == "codex"
    assert executable[0].agent_config.model == "sonnet"

    # Default phase keeps the default provider (claude -p path).
    assert executable[1].agent_config.provider == "claude"


def test_agent_block_rejects_unknown_provider_and_agent_id() -> None:
    """provider and agent_id are constrained at the YAML boundary, so a typo
    like 'codez' fails at parse time instead of after provisioning."""
    bad_provider = """
id: bad-provider-wf
name: Bad Provider Workflow
requires_repos: false

phases:
  - id: p1
    name: Phase 1
    order: 1
    agent:
      provider: claude-interactiv
    prompt_template: Do the thing.
"""
    with pytest.raises(ValueError, match="provider"):
        WorkflowDefinition.from_yaml(bad_provider)

    bad_agent_id = """
id: bad-agent-wf
name: Bad Agent Workflow
requires_repos: false

phases:
  - id: p1
    name: Phase 1
    order: 1
    agent:
      provider: claude-interactive
      agent_id: codez
    prompt_template: Do the thing.
"""
    with pytest.raises(ValueError, match="agent_id"):
        WorkflowDefinition.from_yaml(bad_agent_id)


CODEX_WORKFLOW_YAML = """
id: codex-wf
name: Codex Workflow
requires_repos: false

phases:
  - id: codex-phase
    name: Codex Phase
    order: 1
    agent:
      provider: codex
    prompt_template: Reply with OK.
"""


def test_agent_block_parses_codex_provider() -> None:
    """agent.provider: codex parses and threads through to the domain phase."""
    definition = WorkflowDefinition.from_yaml(CODEX_WORKFLOW_YAML)

    phase = definition.phases[0]
    assert phase.agent is not None
    assert phase.agent.provider == "codex"
    assert phase.agent.agent_id is None

    domain_phase = definition.get_domain_phases()[0]
    assert domain_phase.provider == "codex"
    assert domain_phase.agent_id is None


def test_agent_block_codex_with_explicit_codex_agent_id_parses() -> None:
    """agent_id='codex' is the one explicit value allowed alongside provider=codex."""
    yaml_content = """
id: codex-explicit-wf
name: Codex Explicit Workflow
requires_repos: false

phases:
  - id: p1
    name: Phase 1
    order: 1
    agent:
      provider: codex
      agent_id: codex
    prompt_template: Reply with OK.
"""
    definition = WorkflowDefinition.from_yaml(yaml_content)
    assert definition.phases[0].agent is not None
    assert definition.phases[0].agent.agent_id == "codex"


def test_agent_block_rejects_codex_provider_with_contradicting_agent_id() -> None:
    """provider=codex + agent_id=gemini is a contradiction rejected at parse time."""
    yaml_content = """
id: codex-contradiction-wf
name: Codex Contradiction Workflow
requires_repos: false

phases:
  - id: p1
    name: Phase 1
    order: 1
    agent:
      provider: codex
      agent_id: gemini
    prompt_template: Reply with OK.
"""
    with pytest.raises(ValueError, match="codex"):
        WorkflowDefinition.from_yaml(yaml_content)


def test_agent_block_claude_interactive_with_codex_agent_id_still_parses() -> None:
    """provider=claude-interactive + agent_id=codex is unrelated and still valid."""
    yaml_content = """
id: interactive-codex-wf
name: Interactive Codex Workflow
requires_repos: false

phases:
  - id: p1
    name: Phase 1
    order: 1
    agent:
      provider: claude-interactive
      agent_id: codex
    prompt_template: Reply with OK.
"""
    definition = WorkflowDefinition.from_yaml(yaml_content)
    assert definition.phases[0].agent is not None
    assert definition.phases[0].agent.provider == "claude-interactive"
    assert definition.phases[0].agent.agent_id == "codex"


@pytest.mark.anyio
async def test_codex_provider_reaches_executable_phase_without_agent_id_coercion() -> None:
    """A codex phase must not silently read back agent_id='claude'.

    This is the must-fix regression: `_build_agent_config_from_phase` used to
    fill agent_id from the domain default ("claude") whenever the YAML
    omitted it, so `provider="codex"` silently paired with
    `agent_id="claude"`. AgentConfiguration.agent_id now defaults to None,
    so a codex phase with no agent_id in the YAML must round-trip to
    `agent_id is None`, never `"claude"`.
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

    definition = WorkflowDefinition.from_yaml(CODEX_WORKFLOW_YAML)

    class _StubTemplate:
        phases = definition.get_domain_phases()
        claude_plugins = ()

    handler = ExecuteWorkflowHandler(
        processor=MagicMock(),
        workflow_repository=MagicMock(),
    )
    executable = await handler._get_executable_phases(_StubTemplate())  # type: ignore[arg-type]

    assert executable[0].agent_config.provider == "codex"
    assert executable[0].agent_config.agent_id is None


# =============================================================================
# Mixed-workflow back-compat (codex bridge demo, Task 9)
# =============================================================================

MIXED_PROVIDER_WORKFLOW_YAML = """
id: mixed-provider-wf
name: Mixed Provider Workflow
requires_repos: false

phases:
  - id: claude-phase
    name: Claude Phase
    order: 1
    agent:
      provider: claude
    prompt_template: Reply with CLAUDE_OK.

  - id: claude-interactive-phase
    name: Claude Interactive Phase
    order: 2
    agent:
      provider: claude-interactive
    prompt_template: Reply with CLAUDE_INTERACTIVE_OK.

  - id: codex-phase
    name: Codex Phase
    order: 3
    agent:
      provider: codex
    prompt_template: Reply with CODEX_OK.
"""


def test_mixed_workflow_with_claude_claude_interactive_and_codex_parses() -> None:
    """A workflow mixing all three providers parses without error.

    Proves the back-compat guarantee: adding the codex provider does not
    disturb parsing of pre-existing claude / claude-interactive phases
    when all three appear together in one workflow.
    """
    definition = WorkflowDefinition.from_yaml(MIXED_PROVIDER_WORKFLOW_YAML)

    domain_phases = definition.get_domain_phases()
    assert [p.provider for p in domain_phases] == ["claude", "claude-interactive", "codex"]

    claude_phase, interactive_phase, codex_phase = domain_phases
    assert claude_phase.agent_id is None
    assert interactive_phase.agent_id is None
    assert codex_phase.agent_id is None


def test_codex_demo_example_yaml_loads_and_validates() -> None:
    """workflows/examples/codex-demo.yaml is schema-valid and loads via from_file()."""
    repo_root = Path(__file__).resolve().parents[7]
    demo_path = repo_root / "workflows" / "examples" / "codex-demo.yaml"

    definition = WorkflowDefinition.from_file(demo_path)

    assert definition.id == "codex-demo-workflow-v1"
    assert definition.requires_repos is False
    assert len(definition.phases) == 1

    phase = definition.phases[0]
    assert phase.agent is not None
    assert phase.agent.provider == "codex"
    assert phase.agent.agent_id is None
    assert phase.agent.model == "gpt-5.6"

    domain_phase = definition.get_domain_phases()[0]
    assert domain_phase.provider == "codex"
    assert domain_phase.agent_id is None
