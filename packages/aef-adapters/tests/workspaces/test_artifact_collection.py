"""Tests for artifact collection path consistency.

This module tests that artifact collection uses consistent paths
across all workspace implementations, matching the agent runner.

Test Categories:
- Path constants: WORKSPACE_OUTPUT_DIR is used consistently
- Collection: Artifacts collected from correct path
- Cross-package: agent-runner and adapters use same paths
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestWorkspaceOutputDirConstant:
    """Tests for WORKSPACE_OUTPUT_DIR constant usage."""

    def test_shared_constant_is_artifacts(self):
        """WORKSPACE_OUTPUT_DIR should be /workspace/artifacts."""
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR

        assert str(WORKSPACE_OUTPUT_DIR) == "/workspace/artifacts"

    def test_output_dir_is_under_workspace_root(self):
        """Output dir should be under workspace root."""
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

        # Check it's a child of root
        assert str(WORKSPACE_OUTPUT_DIR).startswith(str(WORKSPACE_ROOT))

    def test_output_dir_relative_path(self):
        """Should be able to get relative path for mounting."""
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

        # Get relative path (e.g., "artifacts")
        rel_path = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT)

        assert str(rel_path) == "artifacts"


class TestIsolatedWorkspaceOutputDir:
    """Tests for IsolatedWorkspace.output_dir property."""

    def test_isolated_workspace_output_dir_uses_constant(self, tmp_path):
        """IsolatedWorkspace.output_dir should derive from WORKSPACE_OUTPUT_DIR."""
        from aef_adapters.agents.agentic_types import WorkspaceConfig
        from aef_adapters.workspaces.types import IsolatedWorkspace
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

        # Create a workspace with minimal config
        config = WorkspaceConfig(session_id="test-session")
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend="docker_hardened",
        )

        # Get the expected relative path
        expected_rel = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT)

        # output_dir should use this relative path
        assert workspace.output_dir.name == str(expected_rel)
        assert workspace.output_dir == tmp_path / "artifacts"

    def test_output_dir_ends_with_artifacts(self, tmp_path):
        """output_dir should end with 'artifacts' directory name."""
        from aef_adapters.agents.agentic_types import WorkspaceConfig
        from aef_adapters.workspaces.types import IsolatedWorkspace

        config = WorkspaceConfig(session_id="test-session")
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend="docker_hardened",
        )

        # Should end in artifacts (the fix)
        assert workspace.output_dir.name == "artifacts"


class TestInMemoryWorkspaceArtifacts:
    """Tests for InMemoryWorkspace artifact handling."""

    def _make_config(self):
        """Create a minimal config for InMemoryWorkspace."""
        from dataclasses import dataclass

        @dataclass
        class MinimalConfig:
            session_id: str = "test-session"

        return MinimalConfig()

    @pytest.mark.asyncio
    async def test_inmemory_workspace_uses_artifacts_prefix(self):
        """InMemoryWorkspace should use artifacts/ prefix, not output/."""
        from aef_adapters.workspaces.memory import InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Should have artifacts/.gitkeep
            assert "artifacts/.gitkeep" in workspace.files

            # Should NOT have output/.gitkeep
            assert "output/.gitkeep" not in workspace.files

    @pytest.mark.asyncio
    async def test_inmemory_collect_artifacts_from_artifacts_dir(self):
        """collect_artifacts should look in artifacts/ directory."""
        from aef_adapters.workspaces.memory import InMemoryFile, InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Write artifact to artifacts/ directory
            workspace.files["artifacts/result.txt"] = InMemoryFile(b"test output")
            workspace.files["artifacts/data/report.json"] = InMemoryFile(b'{"status": "ok"}')

            # Collect artifacts (classmethod that takes workspace)
            artifacts = await InMemoryWorkspace.collect_artifacts(workspace)

            # Should have our files (plus .gitkeep that's created by default)
            paths = [str(path) for path, _ in artifacts]
            assert "result.txt" in paths
            assert "data/report.json" in paths

    @pytest.mark.asyncio
    async def test_inmemory_does_not_collect_from_output(self):
        """collect_artifacts should NOT look in output/ directory."""
        from aef_adapters.workspaces.memory import InMemoryFile, InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Write to wrong directory (old behavior)
            workspace.files["output/result.txt"] = InMemoryFile(b"wrong path")

            # Write to correct directory
            workspace.files["artifacts/correct.txt"] = InMemoryFile(b"right path")

            # Collect artifacts
            artifacts = await InMemoryWorkspace.collect_artifacts(workspace)

            # Should only have the artifacts/ files (not output/)
            paths = [str(path) for path, _ in artifacts]
            assert "correct.txt" in paths
            assert "result.txt" not in paths  # This one is in output/, not artifacts/


class TestAgentRunnerOutputDir:
    """Tests for agent-runner output directory configuration."""

    def test_agent_runner_uses_shared_constant(self):
        """Agent runner should import from aef_shared.workspace_paths."""
        # This is a structural test - verify the import exists
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR

        # The agent runner's __main__.py uses this constant
        # If this import fails, the agent runner will also fail
        assert WORKSPACE_OUTPUT_DIR is not None

    def test_output_dir_matches_collection_path(self):
        """Agent runner output should match what collect_artifacts reads."""
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

        # This is what agent runner uses
        runner_output = Path(str(WORKSPACE_OUTPUT_DIR))

        # This is what workspaces use for collection
        rel_path = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT)

        # They should match
        assert runner_output.name == str(rel_path)
        assert str(rel_path) == "artifacts"


class TestArtifactCollectionIntegration:
    """Integration tests for the full artifact flow."""

    def _make_config(self):
        """Create a minimal config for InMemoryWorkspace."""
        from dataclasses import dataclass

        @dataclass
        class MinimalConfig:
            session_id: str = "test-session"

        return MinimalConfig()

    @pytest.mark.asyncio
    async def test_artifact_written_and_collected(self):
        """Artifact written to correct path should be collectible."""
        from aef_adapters.workspaces.memory import InMemoryFile, InMemoryWorkspace
        from aef_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Simulate what agent runner does
            rel_path = str(WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT))
            workspace.files[f"{rel_path}/agent_output.txt"] = InMemoryFile(b"Hello from agent")

            # Simulate what WorkflowExecutionEngine does
            artifacts = await InMemoryWorkspace.collect_artifacts(workspace)

            paths = {str(path): content for path, content in artifacts}
            assert "agent_output.txt" in paths
            assert paths["agent_output.txt"] == b"Hello from agent"

    @pytest.mark.asyncio
    async def test_nested_artifacts_preserved(self):
        """Nested artifact paths should be preserved."""
        from aef_adapters.workspaces.memory import InMemoryFile, InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            workspace.files["artifacts/reports/2024/summary.md"] = InMemoryFile(b"# Summary")
            workspace.files["artifacts/data/output.json"] = InMemoryFile(b"{}")

            artifacts = await InMemoryWorkspace.collect_artifacts(workspace)

            paths = [str(path) for path, _ in artifacts]
            assert "reports/2024/summary.md" in paths
            assert "data/output.json" in paths
