"""Tests for workspace implementations."""

import json
from pathlib import Path

import pytest

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import LocalWorkspace


class TestLocalWorkspace:
    """Tests for LocalWorkspace."""

    @pytest.fixture
    def workspace_config(self, tmp_path: Path) -> WorkspaceConfig:
        """Create a workspace config using pytest's tmp_path."""
        return WorkspaceConfig(
            session_id="test-session",
            base_dir=tmp_path,
            cleanup_on_exit=False,  # Keep for inspection in tests
        )

    @pytest.mark.asyncio
    async def test_create_workspace_structure(self, workspace_config: WorkspaceConfig) -> None:
        """Workspace should create expected directory structure."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            # Check directories exist
            assert workspace.path.exists()
            assert (workspace.path / ".claude").is_dir()
            assert (workspace.path / ".claude" / "hooks" / "handlers").is_dir()
            assert (workspace.path / ".claude" / "hooks" / "validators").is_dir()
            assert (workspace.path / ".agentic" / "analytics").is_dir()
            assert (workspace.path / ".context").is_dir()
            assert (workspace.path / "output").is_dir()

    @pytest.mark.asyncio
    async def test_create_settings_json(self, workspace_config: WorkspaceConfig) -> None:
        """Workspace should create .claude/settings.json with hook config."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            settings_path = workspace.path / ".claude" / "settings.json"
            assert settings_path.exists()
            
            settings = json.loads(settings_path.read_text())
            assert "hooks" in settings
            assert "PreToolUse" in settings["hooks"]
            assert "PostToolUse" in settings["hooks"]
            assert "UserPromptSubmit" in settings["hooks"]
            
            # Check PreToolUse structure
            pre_tool = settings["hooks"]["PreToolUse"][0]
            assert pre_tool["matcher"] == "*"
            assert len(pre_tool["hooks"]) == 1
            assert pre_tool["hooks"][0]["type"] == "command"

    @pytest.mark.asyncio
    async def test_create_stub_handlers(self, workspace_config: WorkspaceConfig) -> None:
        """Workspace should create stub handlers when hooks source not found."""
        # Use a config with non-existent hooks source
        config = WorkspaceConfig(
            session_id="test-stubs",
            base_dir=workspace_config.base_dir,
            hooks_source=Path("/nonexistent"),
            cleanup_on_exit=False,
        )
        
        async with LocalWorkspace.create(config) as workspace:
            handlers_dir = workspace.path / ".claude" / "hooks" / "handlers"
            
            # Check stub handlers exist and are executable
            pre_tool = handlers_dir / "pre-tool-use.py"
            assert pre_tool.exists()
            assert pre_tool.stat().st_mode & 0o111  # Executable
            
            post_tool = handlers_dir / "post-tool-use.py"
            assert post_tool.exists()
            
            user_prompt = handlers_dir / "user-prompt.py"
            assert user_prompt.exists()

    @pytest.mark.asyncio
    async def test_workspace_path_properties(self, workspace_config: WorkspaceConfig) -> None:
        """Workspace should have correct path properties."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            assert workspace.analytics_path == workspace.path / ".agentic" / "analytics" / "events.jsonl"
            assert workspace.context_dir == workspace.path / ".context"
            assert workspace.output_dir == workspace.path / "output"
            assert workspace.hooks_dir == workspace.path / ".claude" / "hooks"

    @pytest.mark.asyncio
    async def test_inject_context_files(self, workspace_config: WorkspaceConfig) -> None:
        """inject_context should write files to .context directory."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            files = [
                (Path("data.txt"), b"Hello, World!"),
                (Path("nested/config.json"), b'{"key": "value"}'),
            ]
            metadata = {"phase_id": "phase-1", "workflow_id": "wf-123"}
            
            await LocalWorkspace.inject_context(workspace, files, metadata)
            
            # Check files were written
            data_file = workspace.context_dir / "data.txt"
            assert data_file.exists()
            assert data_file.read_bytes() == b"Hello, World!"
            
            nested_file = workspace.context_dir / "nested" / "config.json"
            assert nested_file.exists()
            assert b'"key"' in nested_file.read_bytes()
            
            # Check metadata was written
            context_json = workspace.context_dir / "context.json"
            assert context_json.exists()
            ctx = json.loads(context_json.read_text())
            assert ctx["phase_id"] == "phase-1"

    @pytest.mark.asyncio
    async def test_collect_artifacts_empty(self, workspace_config: WorkspaceConfig) -> None:
        """collect_artifacts should return empty list when no artifacts."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            artifacts = await LocalWorkspace.collect_artifacts(workspace)
            assert artifacts == []

    @pytest.mark.asyncio
    async def test_collect_artifacts_with_files(self, workspace_config: WorkspaceConfig) -> None:
        """collect_artifacts should collect files from output directory."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            # Create some output files
            (workspace.output_dir / "result.txt").write_bytes(b"result data")
            (workspace.output_dir / "nested").mkdir()
            (workspace.output_dir / "nested" / "data.json").write_bytes(b'{"ok": true}')
            
            artifacts = await LocalWorkspace.collect_artifacts(workspace)
            
            assert len(artifacts) == 2
            paths = [str(p) for p, _ in artifacts]
            assert "result.txt" in paths
            assert "nested/data.json" in paths or "nested\\data.json" in paths

    @pytest.mark.asyncio
    async def test_collect_artifacts_with_pattern(self, workspace_config: WorkspaceConfig) -> None:
        """collect_artifacts should filter by patterns."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            # Create mixed output files
            (workspace.output_dir / "result.txt").write_bytes(b"text")
            (workspace.output_dir / "data.json").write_bytes(b'{}')
            (workspace.output_dir / "image.png").write_bytes(b'\x89PNG')
            
            # Collect only JSON files
            artifacts = await LocalWorkspace.collect_artifacts(
                workspace,
                output_patterns=["*.json"],
            )
            
            assert len(artifacts) == 1
            assert artifacts[0][0] == Path("data.json")

    @pytest.mark.asyncio
    async def test_cleanup_on_exit(self, tmp_path: Path) -> None:
        """Workspace should be cleaned up when cleanup_on_exit=True."""
        config = WorkspaceConfig(
            session_id="cleanup-test",
            base_dir=tmp_path,
            cleanup_on_exit=True,
        )
        
        workspace_path = None
        async with LocalWorkspace.create(config) as workspace:
            workspace_path = workspace.path
            assert workspace_path.exists()
        
        # After context exit, workspace should be gone
        assert not workspace_path.exists()

    @pytest.mark.asyncio
    async def test_no_cleanup_on_exit(self, tmp_path: Path) -> None:
        """Workspace should persist when cleanup_on_exit=False."""
        config = WorkspaceConfig(
            session_id="persist-test",
            base_dir=tmp_path,
            cleanup_on_exit=False,
        )
        
        workspace_path = None
        async with LocalWorkspace.create(config) as workspace:
            workspace_path = workspace.path
        
        # After context exit, workspace should still exist
        assert workspace_path.exists()

    @pytest.mark.asyncio
    async def test_session_id_in_path(self, workspace_config: WorkspaceConfig) -> None:
        """Workspace path should contain session_id for identification."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            assert "test-session" in str(workspace.path)

    @pytest.mark.asyncio
    async def test_workspace_config_stored(self, workspace_config: WorkspaceConfig) -> None:
        """Workspace should store its config for reference."""
        async with LocalWorkspace.create(workspace_config) as workspace:
            assert workspace.config == workspace_config
            assert workspace.config.session_id == "test-session"

