"""Round-trip test: export workflow → resolve_package() → compare with original.

This is the critical test ensuring exported packages are re-importable
via `syn workflow install` and produce equivalent workflows.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from syn_api.types import Ok

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


async def _create_workflow_with_phases() -> str:
    """Create a test workflow with rich phase definitions."""
    from syn_api.routes.workflows import create_workflow

    result = await create_workflow(
        name="Roundtrip Test",
        workflow_type="research",
        description="Workflow for round-trip testing",
        phases=[
            {
                "phase_id": "discovery",
                "name": "Discovery",
                "order": 1,
                "prompt_template": "Research the topic thoroughly.\n\nConsider:\n- Scope\n- Sources\n- Key questions",
                "allowed_tools": ["Read", "Grep", "Bash"],
                "model": "sonnet",
                "argument_hint": "[research topic]",
                "timeout_seconds": 600,
            },
            {
                "phase_id": "deep-dive",
                "name": "Deep Dive",
                "order": 2,
                "prompt_template": "Deep dive into the findings from discovery phase.",
                "allowed_tools": ["Read", "Write", "Bash"],
                "model": "opus",
                "timeout_seconds": 900,
            },
            {
                "phase_id": "synthesis",
                "name": "Synthesis",
                "order": 3,
                "prompt_template": "Synthesize all findings into a coherent report.",
                "allowed_tools": ["Write"],
                "model": "sonnet",
            },
        ],
    )
    assert isinstance(result, Ok)
    return result.value


@pytest.mark.unit
class TestExportImportRoundtrip:
    """Export a workflow, write to disk, then resolve_package() and compare."""

    async def test_package_roundtrip_preserves_phases(self, tmp_path: Path) -> None:
        """Package format: export → write → resolve_package → compare."""
        from syn_api.routes.workflows import export_workflow, get_workflow
        from syn_cli.commands._package_resolver import resolve_package

        wf_id = await _create_workflow_with_phases()

        # Get original workflow detail
        original = await get_workflow(wf_id)
        assert isinstance(original, Ok)
        original_detail = original.value

        # Export
        export_result = await export_workflow(wf_id, fmt="package")
        assert isinstance(export_result, Ok)
        manifest = export_result.value

        # Write files to disk
        out_dir = tmp_path / "roundtrip-pkg"
        for rel_path, content in manifest.files.items():
            file_path = out_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        # Re-import via resolve_package
        _, resolved_workflows = resolve_package(out_dir)

        assert len(resolved_workflows) == 1
        resolved = resolved_workflows[0]

        # Compare core fields
        assert resolved.name == original_detail.name
        assert resolved.workflow_type == original_detail.workflow_type
        assert resolved.classification == original_detail.classification

        # Compare phases
        assert len(resolved.phases) == len(original_detail.phases)
        for orig_phase, resolved_phase_dict in zip(
            sorted(original_detail.phases, key=lambda p: p.order),
            sorted(resolved.phases, key=lambda p: p.get("order", 0)),  # type: ignore[union-attr]
            strict=True,
        ):
            assert resolved_phase_dict["phase_id"] == orig_phase.phase_id
            assert resolved_phase_dict["name"] == orig_phase.name
            assert resolved_phase_dict["order"] == orig_phase.order
            assert resolved_phase_dict["prompt_template"] == orig_phase.prompt_template

            # Frontmatter fields round-trip through kebab→snake conversion
            assert resolved_phase_dict["model"] == orig_phase.model
            assert list(resolved_phase_dict["allowed_tools"]) == list(orig_phase.allowed_tools)

            if orig_phase.argument_hint:
                assert resolved_phase_dict["argument_hint"] == orig_phase.argument_hint

            if orig_phase.timeout_seconds and orig_phase.timeout_seconds != 300:
                assert resolved_phase_dict["timeout_seconds"] == orig_phase.timeout_seconds

    async def test_plugin_roundtrip_preserves_phases(self, tmp_path: Path) -> None:
        """Plugin format: export → write → resolve_package → compare."""
        from syn_api.routes.workflows import export_workflow, get_workflow
        from syn_cli.commands._package_resolver import resolve_package

        wf_id = await _create_workflow_with_phases()

        original = await get_workflow(wf_id)
        assert isinstance(original, Ok)
        original_detail = original.value

        # Export as plugin
        export_result = await export_workflow(wf_id, fmt="plugin")
        assert isinstance(export_result, Ok)
        manifest = export_result.value

        # Write files to disk
        out_dir = tmp_path / "roundtrip-plugin"
        for rel_path, content in manifest.files.items():
            file_path = out_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        # Re-import via resolve_package (should detect multi-workflow format)
        _, resolved_workflows = resolve_package(out_dir)

        assert len(resolved_workflows) == 1
        resolved = resolved_workflows[0]

        # Compare core fields
        assert resolved.name == original_detail.name
        assert resolved.workflow_type == original_detail.workflow_type

        # Compare phase count and prompts
        assert len(resolved.phases) == len(original_detail.phases)
        for orig_phase, resolved_phase_dict in zip(
            sorted(original_detail.phases, key=lambda p: p.order),
            sorted(resolved.phases, key=lambda p: p.get("order", 0)),  # type: ignore[union-attr]
            strict=True,
        ):
            assert resolved_phase_dict["prompt_template"] == orig_phase.prompt_template

    async def test_multiline_prompt_survives_roundtrip(self, tmp_path: Path) -> None:
        """Prompts with newlines, special chars should survive export/import."""
        from syn_api.routes.workflows import create_workflow, export_workflow
        from syn_cli.commands._package_resolver import resolve_package

        result = await create_workflow(
            name="Multiline Test",
            workflow_type="custom",
            phases=[
                {
                    "phase_id": "complex",
                    "name": "Complex",
                    "order": 1,
                    "prompt_template": (
                        "Line one.\n\n"
                        "## Section\n\n"
                        "- Bullet 1\n"
                        "- Bullet 2\n\n"
                        "```python\nprint('hello')\n```\n\n"
                        "$ARGUMENTS"
                    ),
                },
            ],
        )
        assert isinstance(result, Ok)

        export_result = await export_workflow(result.value, fmt="package")
        assert isinstance(export_result, Ok)

        out_dir = tmp_path / "multiline"
        for rel_path, content in export_result.value.files.items():
            file_path = out_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        _, resolved = resolve_package(out_dir)
        assert len(resolved) == 1
        phase = resolved[0].phases[0]
        original_prompt = (
            "Line one.\n\n"
            "## Section\n\n"
            "- Bullet 1\n"
            "- Bullet 2\n\n"
            "```python\nprint('hello')\n```\n\n"
            "$ARGUMENTS"
        )
        assert phase["prompt_template"] == original_prompt
