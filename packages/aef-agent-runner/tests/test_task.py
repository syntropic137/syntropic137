"""Tests for task module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from aef_agent_runner.task import Task


class TestTask:
    """Tests for Task class."""

    def test_from_file_valid(self, tmp_path: Path) -> None:
        """Should load valid task file."""
        task_data = {
            "phase": "research",
            "prompt": "Research best practices",
            "execution_id": "exec-123",
            "tenant_id": "tenant-abc",
            "inputs": {"topic": "testing"},
            "artifacts": ["previous.md"],
        }
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task_data))

        task = Task.from_file(task_file)

        assert task.phase == "research"
        assert task.prompt == "Research best practices"
        assert task.execution_id == "exec-123"
        assert task.tenant_id == "tenant-abc"
        assert task.inputs == {"topic": "testing"}
        assert task.artifacts == ["previous.md"]

    def test_from_file_minimal(self, tmp_path: Path) -> None:
        """Should load task with only required fields."""
        task_data = {
            "phase": "implement",
            "prompt": "Implement the feature",
            "execution_id": "exec-456",
            "tenant_id": "tenant-xyz",
        }
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task_data))

        task = Task.from_file(task_file)

        assert task.phase == "implement"
        assert task.inputs == {}
        assert task.artifacts == []
        assert task.config == {}

    def test_from_file_missing_required(self, tmp_path: Path) -> None:
        """Should raise ValueError for missing required fields."""
        task_data = {
            "phase": "test",
            # Missing: prompt, execution_id, tenant_id
        }
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task_data))

        with pytest.raises(ValueError, match="Missing required fields"):
            Task.from_file(task_file)

    def test_from_file_not_found(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing file."""
        task_file = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            Task.from_file(task_file)

    def test_from_file_invalid_json(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid JSON."""
        task_file = tmp_path / "task.json"
        task_file.write_text("not valid json")

        with pytest.raises(ValueError, match="Invalid JSON"):
            Task.from_file(task_file)

    def test_get_artifact_paths(self, tmp_path: Path) -> None:
        """Should return full paths to artifacts."""
        task = Task(
            phase="test",
            prompt="Test",
            execution_id="exec-1",
            tenant_id="tenant-1",
            artifacts=["file1.md", "file2.json"],
        )
        inputs_dir = tmp_path / "inputs"

        paths = task.get_artifact_paths(inputs_dir)

        assert len(paths) == 2
        assert paths[0] == inputs_dir / "file1.md"
        assert paths[1] == inputs_dir / "file2.json"

    def test_build_system_prompt(self) -> None:
        """Should build system prompt with context."""
        task = Task(
            phase="research",
            prompt="Research the topic",
            execution_id="exec-1",
            tenant_id="tenant-1",
            inputs={"topic": "AI safety"},
            artifacts=["background.md"],
        )

        prompt = task.build_system_prompt()

        assert "Research the topic" in prompt
        assert "/workspace/inputs/background.md" in prompt
        assert "topic" in prompt
        assert "AI safety" in prompt
        assert "/workspace/artifacts/" in prompt

    def test_build_system_prompt_minimal(self) -> None:
        """Should build system prompt with no artifacts or inputs."""
        task = Task(
            phase="simple",
            prompt="Do something simple",
            execution_id="exec-1",
            tenant_id="tenant-1",
        )

        prompt = task.build_system_prompt()

        assert "Do something simple" in prompt
        assert "/workspace/artifacts/" in prompt
        assert "Available Input Artifacts" not in prompt
        assert "Workflow Inputs" not in prompt
