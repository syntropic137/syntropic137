"""Tests for shared:// prompt resolution in workflow definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    _resolve_phase_prompt_file,
)


@pytest.mark.unit
class TestSharedPromptResolution:
    """Tests for the shared:// prompt_file prefix."""

    def test_resolve_shared_prompt(self, tmp_path: Path) -> None:
        """shared://name resolves to phase-library/name.md."""
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()
        (lib_dir / "summarize.md").write_text(
            "---\nmodel: sonnet\nmax-tokens: 2048\n---\n\nSummarize the work.\n"
        )

        phase: dict[str, object] = {
            "id": "summarize",
            "name": "Summarize",
            "order": 1,
            "prompt_file": "shared://summarize",
        }

        _resolve_phase_prompt_file(phase, tmp_path, phase_library_dir=lib_dir)

        assert phase["prompt_template"] == "Summarize the work."
        assert "prompt_file" not in phase
        # Frontmatter should be merged
        assert phase["model"] == "sonnet"
        assert phase["max_tokens"] == 2048

    def test_shared_without_library_raises(self, tmp_path: Path) -> None:
        """shared:// without phase_library_dir raises ValueError."""
        phase: dict[str, object] = {
            "id": "test",
            "name": "Test",
            "order": 1,
            "prompt_file": "shared://something",
        }

        with pytest.raises(ValueError, match="requires a phase-library directory"):
            _resolve_phase_prompt_file(phase, tmp_path, phase_library_dir=None)

    def test_shared_empty_reference_raises(self, tmp_path: Path) -> None:
        """shared:// with empty name raises ValueError."""
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()

        phase: dict[str, object] = {
            "id": "test",
            "name": "Test",
            "order": 1,
            "prompt_file": "shared://",
        }

        with pytest.raises(ValueError, match="empty"):
            _resolve_phase_prompt_file(phase, tmp_path, phase_library_dir=lib_dir)

    def test_shared_path_traversal_rejected(self, tmp_path: Path) -> None:
        """shared:// must not escape the phase-library directory."""
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()

        phase: dict[str, object] = {
            "id": "evil",
            "name": "Evil",
            "order": 1,
            "prompt_file": "shared://../../etc/passwd",
        }

        with pytest.raises(ValueError, match="escapes phase-library"):
            _resolve_phase_prompt_file(phase, tmp_path, phase_library_dir=lib_dir)

    def test_shared_yaml_values_take_precedence(self, tmp_path: Path) -> None:
        """YAML phase values should override .md frontmatter."""
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()
        (lib_dir / "action.md").write_text(
            "---\nmodel: sonnet\nmax-tokens: 2048\n---\n\nDo the action.\n"
        )

        phase: dict[str, object] = {
            "id": "action",
            "name": "Action",
            "order": 1,
            "prompt_file": "shared://action",
            "model": "opus",  # YAML override
        }

        _resolve_phase_prompt_file(phase, tmp_path, phase_library_dir=lib_dir)

        assert phase["model"] == "opus"  # YAML wins
        assert phase["max_tokens"] == 2048  # Frontmatter fills gap

    def test_from_file_with_phase_library(self, tmp_path: Path) -> None:
        """WorkflowDefinition.from_file() accepts phase_library_dir."""
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()
        (lib_dir / "shared-phase.md").write_text(
            "---\nmodel: sonnet\n---\n\nShared prompt content.\n"
        )

        (tmp_path / "workflow.yaml").write_text(
            """\
id: shared-test-v1
name: Shared Test
type: research
classification: standard
phases:
  - id: shared-phase
    name: Shared Phase
    order: 1
    prompt_file: shared://shared-phase
"""
        )

        defn = WorkflowDefinition.from_file(
            tmp_path / "workflow.yaml",
            phase_library_dir=lib_dir,
        )

        assert len(defn.phases) == 1
        assert defn.phases[0].prompt_template == "Shared prompt content."
        assert defn.phases[0].model == "sonnet"

    def test_regular_prompt_file_still_works(self, tmp_path: Path) -> None:
        """Non-shared:// prompt_file paths continue to work as before."""
        phases_dir = tmp_path / "phases"
        phases_dir.mkdir()
        (phases_dir / "local.md").write_text("---\nmodel: haiku\n---\n\nLocal prompt.\n")

        (tmp_path / "workflow.yaml").write_text(
            """\
id: local-test-v1
name: Local Test
type: custom
classification: simple
phases:
  - id: local
    name: Local
    order: 1
    prompt_file: phases/local.md
"""
        )

        defn = WorkflowDefinition.from_file(tmp_path / "workflow.yaml")
        assert defn.phases[0].prompt_template == "Local prompt."
        assert defn.phases[0].model == "haiku"
