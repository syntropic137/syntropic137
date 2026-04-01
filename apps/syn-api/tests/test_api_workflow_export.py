"""Tests for workflow export service — export_workflow() with in-memory storage."""

import os

import pytest

from syn_api.types import Err, Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _create_test_workflow(
    name: str = "Deep Research",
    workflow_type: str = "research",
    description: str = "Multi-phase research workflow",
    phases: list[dict[str, object]] | None = None,
) -> str:
    """Create a test workflow and return its ID."""
    from syn_api.routes.workflows import create_workflow

    if phases is None:
        phases = [
            {
                "phase_id": "discovery",
                "name": "Discovery",
                "order": 1,
                "prompt_template": "Research the topic: $ARGUMENTS",
                "allowed_tools": ["Read", "Grep", "Bash"],
                "model": "sonnet",
                "argument_hint": "[topic]",
                "timeout_seconds": 600,
            },
            {
                "phase_id": "synthesis",
                "name": "Synthesis",
                "order": 2,
                "prompt_template": "Synthesize findings from the discovery phase.",
                "allowed_tools": ["Read", "Write"],
                "model": "opus",
            },
        ]

    result = await create_workflow(
        name=name,
        workflow_type=workflow_type,
        description=description,
        phases=phases,
    )
    assert isinstance(result, Ok)
    return result.value


# -- Package format ---


async def test_export_package_format():
    """Export in package format produces workflow.yaml, README, and phase .md files."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow()
    result = await export_workflow(wf_id, fmt="package")

    assert isinstance(result, Ok)
    manifest = result.value
    assert manifest.format == "package"
    assert manifest.workflow_id == wf_id
    assert manifest.workflow_name == "Deep Research"

    files = manifest.files
    assert "workflow.yaml" in files
    assert "README.md" in files
    assert "phases/discovery.md" in files
    assert "phases/synthesis.md" in files


async def test_export_package_workflow_yaml_has_prompt_file_refs():
    """workflow.yaml should reference prompt_file, not inline prompt_template."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow()
    result = await export_workflow(wf_id, fmt="package")
    assert isinstance(result, Ok)

    yaml_content = result.value.files["workflow.yaml"]
    assert "prompt_file: phases/discovery.md" in yaml_content
    assert "prompt_file: phases/synthesis.md" in yaml_content
    # Should NOT have inline prompt_template in the YAML
    assert "prompt_template:" not in yaml_content


async def test_export_package_phase_md_has_frontmatter():
    """Phase .md files should have kebab-case YAML frontmatter."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow()
    result = await export_workflow(wf_id, fmt="package")
    assert isinstance(result, Ok)

    discovery_md = result.value.files["phases/discovery.md"]

    # Should have frontmatter delimiters
    assert discovery_md.startswith("---\n")
    assert "\n---\n" in discovery_md

    # Should have kebab-case keys (matching md_prompt_loader.py expectations)
    assert "model: sonnet" in discovery_md
    assert 'argument-hint: "[topic]"' in discovery_md
    assert "allowed-tools: Read,Grep,Bash" in discovery_md
    assert "timeout-seconds: 600" in discovery_md

    # Body should be the prompt template
    assert "Research the topic: $ARGUMENTS" in discovery_md


async def test_export_package_phase_without_optional_fields():
    """Phase with minimal fields should produce clean frontmatter."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow(
        phases=[
            {
                "phase_id": "simple",
                "name": "Simple",
                "order": 1,
                "prompt_template": "Do the thing.",
            },
        ],
    )
    result = await export_workflow(wf_id, fmt="package")
    assert isinstance(result, Ok)

    simple_md = result.value.files["phases/simple.md"]
    # No frontmatter if no optional fields set
    assert "Do the thing." in simple_md
    assert "model:" not in simple_md
    assert "argument-hint:" not in simple_md


# -- Plugin format ---


async def test_export_plugin_format():
    """Export in plugin format produces manifest, commands, and workflow subdirectory."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow()
    result = await export_workflow(wf_id, fmt="plugin")

    assert isinstance(result, Ok)
    manifest = result.value
    assert manifest.format == "plugin"

    files = manifest.files
    assert "syntropic137-plugin.json" in files
    assert "README.md" in files
    assert "commands/syn-deep-research.md" in files
    assert "workflows/deep-research/workflow.yaml" in files
    assert "workflows/deep-research/phases/discovery.md" in files
    assert "workflows/deep-research/phases/synthesis.md" in files


async def test_export_plugin_manifest_content():
    """syntropic137-plugin.json should have correct manifest fields."""
    import json

    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow()
    result = await export_workflow(wf_id, fmt="plugin")
    assert isinstance(result, Ok)

    manifest_json = result.value.files["syntropic137-plugin.json"]
    manifest = json.loads(manifest_json)
    assert manifest["manifest_version"] == 1
    assert manifest["name"] == "deep-research"
    assert manifest["version"] == "0.1.0"


async def test_export_plugin_cc_command():
    """Claude Code command wrapper should reference syn workflow run."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow()
    result = await export_workflow(wf_id, fmt="plugin")
    assert isinstance(result, Ok)

    cmd_md = result.value.files["commands/syn-deep-research.md"]
    assert "---" in cmd_md
    assert "model: sonnet" in cmd_md
    assert "allowed-tools: Bash" in cmd_md
    assert f"syn workflow run {wf_id}" in cmd_md
    assert "$ARGUMENTS" in cmd_md


# -- Error handling ---


async def test_export_workflow_not_found():
    """Export of nonexistent workflow returns Err."""
    from syn_api.routes.workflows import export_workflow

    result = await export_workflow("nonexistent-id", fmt="package")
    assert isinstance(result, Err)


async def test_export_package_preserves_execution_type():
    """Non-sequential execution_type should appear in workflow.yaml."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow(
        phases=[
            {
                "phase_id": "parallel-phase",
                "name": "Parallel",
                "order": 1,
                "execution_type": "parallel",
                "prompt_template": "Run in parallel.",
            },
        ],
    )
    result = await export_workflow(wf_id, fmt="package")
    assert isinstance(result, Ok)

    yaml_content = result.value.files["workflow.yaml"]
    assert "execution_type: parallel" in yaml_content


async def test_export_package_preserves_max_tokens():
    """max_tokens should appear in phase .md frontmatter."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow(
        phases=[
            {
                "phase_id": "limited",
                "name": "Limited",
                "order": 1,
                "prompt_template": "Work carefully.",
                "max_tokens": 4096,
            },
        ],
    )
    result = await export_workflow(wf_id, fmt="package")
    assert isinstance(result, Ok)

    phase_md = result.value.files["phases/limited.md"]
    assert "max-tokens: 4096" in phase_md


async def test_export_workflow_with_input_declarations():
    """Input declarations should appear in workflow.yaml."""
    from syn_api.routes.workflows import export_workflow

    wf_id = await _create_test_workflow(
        phases=[
            {
                "phase_id": "run",
                "name": "Run",
                "order": 1,
                "prompt_template": "Execute: $ARGUMENTS",
            },
        ],
    )
    # TODO(#400): Input declarations are passed at create time, verify they
    # round-trip through the projection. For now, test that the export
    # succeeds and produces valid structure.
    result = await export_workflow(wf_id, fmt="package")
    assert isinstance(result, Ok)
    assert "workflow.yaml" in result.value.files
