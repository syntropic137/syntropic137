"""Tests for workspace_paths module.

These tests verify the type-safe workspace path constants are correct
and consistent across the codebase.
"""

from pathlib import PurePosixPath

import pytest


class TestWorkspacePathConstants:
    """Test workspace path constants are correctly defined."""

    def test_workspace_root_is_posix_path(self):
        """WORKSPACE_ROOT should be a PurePosixPath."""
        from aef_shared.workspace_paths import WORKSPACE_ROOT

        assert isinstance(WORKSPACE_ROOT, PurePosixPath)
        assert str(WORKSPACE_ROOT) == "/workspace"

    def test_workspace_output_dir(self):
        """WORKSPACE_OUTPUT_DIR should be /workspace/artifacts."""
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR

        assert isinstance(WORKSPACE_OUTPUT_DIR, PurePosixPath)
        assert str(WORKSPACE_OUTPUT_DIR) == "/workspace/artifacts"

    def test_workspace_context_dir(self):
        """WORKSPACE_CONTEXT_DIR should be /workspace/.context."""
        from aef_shared.workspace_paths import WORKSPACE_CONTEXT_DIR

        assert isinstance(WORKSPACE_CONTEXT_DIR, PurePosixPath)
        assert str(WORKSPACE_CONTEXT_DIR) == "/workspace/.context"

    def test_workspace_task_file(self):
        """WORKSPACE_TASK_FILE should be /workspace/.context/task.json."""
        from aef_shared.workspace_paths import WORKSPACE_TASK_FILE

        assert isinstance(WORKSPACE_TASK_FILE, PurePosixPath)
        assert str(WORKSPACE_TASK_FILE) == "/workspace/.context/task.json"

    def test_workspace_analytics_dir(self):
        """WORKSPACE_ANALYTICS_DIR should be /workspace/.agentic/analytics."""
        from aef_shared.workspace_paths import WORKSPACE_ANALYTICS_DIR

        assert isinstance(WORKSPACE_ANALYTICS_DIR, PurePosixPath)
        assert str(WORKSPACE_ANALYTICS_DIR) == "/workspace/.agentic/analytics"

    def test_workspace_analytics_file(self):
        """WORKSPACE_ANALYTICS_FILE should be /workspace/.agentic/analytics/events.jsonl."""
        from aef_shared.workspace_paths import WORKSPACE_ANALYTICS_FILE

        assert isinstance(WORKSPACE_ANALYTICS_FILE, PurePosixPath)
        assert str(WORKSPACE_ANALYTICS_FILE) == "/workspace/.agentic/analytics/events.jsonl"

    def test_workspace_claude_dir(self):
        """WORKSPACE_CLAUDE_DIR should be /workspace/.claude."""
        from aef_shared.workspace_paths import WORKSPACE_CLAUDE_DIR

        assert isinstance(WORKSPACE_CLAUDE_DIR, PurePosixPath)
        assert str(WORKSPACE_CLAUDE_DIR) == "/workspace/.claude"

    def test_workspace_hooks_dir(self):
        """WORKSPACE_HOOKS_DIR should be /workspace/.claude/hooks."""
        from aef_shared.workspace_paths import WORKSPACE_HOOKS_DIR

        assert isinstance(WORKSPACE_HOOKS_DIR, PurePosixPath)
        assert str(WORKSPACE_HOOKS_DIR) == "/workspace/.claude/hooks"

    def test_workspace_settings_file(self):
        """WORKSPACE_SETTINGS_FILE should be /workspace/.claude/settings.json."""
        from aef_shared.workspace_paths import WORKSPACE_SETTINGS_FILE

        assert isinstance(WORKSPACE_SETTINGS_FILE, PurePosixPath)
        assert str(WORKSPACE_SETTINGS_FILE) == "/workspace/.claude/settings.json"

    def test_workspace_logs_dir(self):
        """WORKSPACE_LOGS_DIR should be /workspace/.logs."""
        from aef_shared.workspace_paths import WORKSPACE_LOGS_DIR

        assert isinstance(WORKSPACE_LOGS_DIR, PurePosixPath)
        assert str(WORKSPACE_LOGS_DIR) == "/workspace/.logs"


class TestWorkspacePathRelationships:
    """Test that workspace paths have correct parent-child relationships."""

    def test_output_dir_is_child_of_root(self):
        """WORKSPACE_OUTPUT_DIR should be a child of WORKSPACE_ROOT."""
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

        rel_path = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT)
        assert str(rel_path) == "artifacts"

    def test_context_dir_is_child_of_root(self):
        """WORKSPACE_CONTEXT_DIR should be a child of WORKSPACE_ROOT."""
        from aef_shared.workspace_paths import WORKSPACE_CONTEXT_DIR, WORKSPACE_ROOT

        rel_path = WORKSPACE_CONTEXT_DIR.relative_to(WORKSPACE_ROOT)
        assert str(rel_path) == ".context"

    def test_task_file_is_in_context_dir(self):
        """WORKSPACE_TASK_FILE should be inside WORKSPACE_CONTEXT_DIR."""
        from aef_shared.workspace_paths import WORKSPACE_CONTEXT_DIR, WORKSPACE_TASK_FILE

        rel_path = WORKSPACE_TASK_FILE.relative_to(WORKSPACE_CONTEXT_DIR)
        assert str(rel_path) == "task.json"

    def test_hooks_dir_is_in_claude_dir(self):
        """WORKSPACE_HOOKS_DIR should be inside WORKSPACE_CLAUDE_DIR."""
        from aef_shared.workspace_paths import WORKSPACE_CLAUDE_DIR, WORKSPACE_HOOKS_DIR

        rel_path = WORKSPACE_HOOKS_DIR.relative_to(WORKSPACE_CLAUDE_DIR)
        assert str(rel_path) == "hooks"


class TestWorkspacePathExports:
    """Test that all constants are properly exported."""

    def test_all_exports_from_module(self):
        """All constants should be in __all__."""
        from aef_shared import workspace_paths

        expected_exports = [
            "WORKSPACE_ROOT",
            "WORKSPACE_OUTPUT_DIR",
            "WORKSPACE_CONTEXT_DIR",
            "WORKSPACE_TASK_FILE",
            "WORKSPACE_ANALYTICS_DIR",
            "WORKSPACE_ANALYTICS_FILE",
            "WORKSPACE_CLAUDE_DIR",
            "WORKSPACE_HOOKS_DIR",
            "WORKSPACE_SETTINGS_FILE",
            "WORKSPACE_LOGS_DIR",
        ]

        for export in expected_exports:
            assert export in workspace_paths.__all__, f"{export} not in __all__"
            assert hasattr(workspace_paths, export), f"{export} not defined"

    def test_exports_from_package(self):
        """Constants should be importable from aef_shared package."""
        from aef_shared import (
            WORKSPACE_CONTEXT_DIR,
            WORKSPACE_OUTPUT_DIR,
            WORKSPACE_ROOT,
            WORKSPACE_TASK_FILE,
        )

        # Basic sanity check
        assert str(WORKSPACE_ROOT) == "/workspace"
        assert str(WORKSPACE_OUTPUT_DIR) == "/workspace/artifacts"
        assert str(WORKSPACE_CONTEXT_DIR) == "/workspace/.context"
        assert str(WORKSPACE_TASK_FILE) == "/workspace/.context/task.json"
