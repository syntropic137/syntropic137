"""Tests for runner module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from aef_agent_runner.cancellation import CancellationToken
from aef_agent_runner.runner import AgentRunner
from aef_agent_runner.task import Task


class TestAgentRunner:
    """Tests for AgentRunner class."""

    @pytest.fixture
    def task(self) -> Task:
        """Create a test task."""
        return Task(
            phase="test",
            prompt="Test the system",
            execution_id="exec-test-123",
            tenant_id="tenant-test",
            inputs={"key": "value"},
            artifacts=[],
        )

    @pytest.fixture
    def output_dir(self, tmp_path: Path) -> Path:
        """Create output directory."""
        out = tmp_path / "artifacts"
        out.mkdir()
        return out

    @pytest.fixture
    def cancel_token(self, tmp_path: Path) -> CancellationToken:
        """Create cancellation token."""
        return CancellationToken(tmp_path / ".cancel")

    def test_init(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should initialize runner correctly."""
        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        assert runner._task == task
        assert runner._output_dir == output_dir
        assert runner._cancel_token == cancel_token
        assert runner._turn_count == 0

    def test_init_creates_output_dir(
        self,
        task: Task,
        tmp_path: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should create output directory if it doesn't exist."""
        output_dir = tmp_path / "new_artifacts"
        assert not output_dir.exists()

        AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        assert output_dir.exists()

    def test_build_task_prompt(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should build task prompt with task context."""
        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        message = runner._build_task_prompt()

        # Prompt from task
        assert "Test the system" in message
        # Inputs section
        assert "key" in message
        assert "value" in message
        # Output instructions
        assert "/workspace/artifacts/" in message

    def test_collect_artifacts_emits_events(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should emit artifact events for files in output dir."""
        # Create some output files
        (output_dir / "file1.md").write_text("# Test")
        (output_dir / "file2.json").write_text('{"key": "value"}')

        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        # Collect and verify events are emitted
        with mock.patch("aef_agent_runner.runner.emit_artifact") as mock_emit:
            runner._collect_artifacts()

            assert mock_emit.call_count == 2

    def test_collect_artifacts_handles_subdirs(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should handle files in subdirectories."""
        subdir = output_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")

        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        with mock.patch("aef_agent_runner.runner.emit_artifact") as mock_emit:
            runner._collect_artifacts()

            assert mock_emit.call_count == 1
            call_args = mock_emit.call_args
            assert "subdir/nested.txt" in call_args[1]["name"]
