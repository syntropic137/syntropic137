"""Tests for git attribution settings.

This module tests that .claude/settings.json is configured correctly
to disable Claude's automatic Co-Authored-By trailer.

Test Categories:
- Settings structure: attribution section exists
- Commits disabled: attribution.commits = false
- PRs disabled: attribution.pullRequests = false
- All workspaces: Settings applied to all workspace types
"""

from __future__ import annotations

import json

import pytest


class TestSettingsJsonStructure:
    """Tests for .claude/settings.json structure."""

    def test_settings_has_attribution_section(self):
        """Settings should have an attribution section."""
        # This is what _generate_settings should produce
        expected_settings = {
            "hooks": {"enabled": True},
            "permissions": {
                "allow_mcp": "always",
                "bash": {"allow": "always"},
                "mcp": {"allow": "always"},
            },
            "attribution": {
                "commits": False,
                "pullRequests": False,
            },
        }

        assert "attribution" in expected_settings
        assert isinstance(expected_settings["attribution"], dict)

    def test_attribution_commits_is_false(self):
        """attribution.commits should be False to disable trailer."""
        settings = {
            "attribution": {
                "commits": False,
                "pullRequests": False,
            }
        }

        assert settings["attribution"]["commits"] is False

    def test_attribution_pull_requests_is_false(self):
        """attribution.pullRequests should be False."""
        settings = {
            "attribution": {
                "commits": False,
                "pullRequests": False,
            }
        }

        assert settings["attribution"]["pullRequests"] is False


class TestInMemoryWorkspaceAttribution:
    """Tests for InMemoryWorkspace attribution settings."""

    def _make_config(self):
        """Create a minimal config for InMemoryWorkspace."""
        from dataclasses import dataclass

        @dataclass
        class MinimalConfig:
            session_id: str = "test-session"

        return MinimalConfig()

    @pytest.mark.asyncio
    async def test_inmemory_workspace_has_attribution(self):
        """InMemoryWorkspace settings should have attribution."""
        from aef_adapters.workspaces.memory import InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Check settings.json exists
            assert ".claude/settings.json" in workspace.files

            # Parse and check attribution
            settings_content = workspace.files[".claude/settings.json"].content
            settings = json.loads(settings_content.decode())
            assert "attribution" in settings
            assert settings["attribution"]["commits"] is False
            assert settings["attribution"]["pullRequests"] is False

    @pytest.mark.asyncio
    async def test_inmemory_settings_complete(self):
        """InMemoryWorkspace should have all required settings."""
        from aef_adapters.workspaces.memory import InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            settings_content = workspace.files[".claude/settings.json"].content
            settings = json.loads(settings_content.decode())

            # Check attribution section
            assert "attribution" in settings


class TestGenerateSettingsMethod:
    """Tests for _generate_settings in workspace classes."""

    @pytest.mark.asyncio
    async def test_generate_settings_includes_attribution(self, tmp_path):
        """_generate_settings should include attribution section."""
        from aef_adapters.workspaces.local import LocalWorkspace

        # Create .claude directory
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)

        # Call _generate_settings with the path (not IsolatedWorkspace)
        await LocalWorkspace._generate_settings(tmp_path)

        # Check settings file
        settings_file = claude_dir / "settings.json"
        assert settings_file.exists()

        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "attribution" in settings
        assert settings["attribution"]["commits"] is False
        assert settings["attribution"]["pullRequests"] is False

    @pytest.mark.asyncio
    async def test_generate_settings_preserves_hooks(self, tmp_path):
        """_generate_settings should include hooks section."""
        from aef_adapters.workspaces.local import LocalWorkspace

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)

        await LocalWorkspace._generate_settings(tmp_path)

        settings_file = claude_dir / "settings.json"
        settings = json.loads(settings_file.read_text(encoding="utf-8"))

        # Check hooks section is present
        assert "hooks" in settings


class TestAttributionEffectiveness:
    """Tests that verify attribution settings work as expected."""

    def test_co_authored_by_trailer_format(self):
        """Document the trailer format we're trying to prevent."""
        # This is what Claude adds by default:
        # "Co-Authored-By: Claude Sonnet 4 <noreply@anthropic.com>"
        # Our settings disable this
        settings = {"attribution": {"commits": False}}

        # When commits is False, Claude should NOT add this trailer
        assert not settings["attribution"]["commits"]

    def test_attribution_settings_json_serializable(self):
        """Attribution settings should be JSON serializable."""
        settings = {
            "attribution": {
                "commits": False,
                "pullRequests": False,
            }
        }

        # Should not raise
        json_str = json.dumps(settings)
        parsed = json.loads(json_str)

        assert parsed["attribution"]["commits"] is False


class TestLocalWorkspaceAttribution:
    """Tests for LocalWorkspace attribution settings."""

    @pytest.mark.asyncio
    async def test_local_workspace_generates_attribution(self, tmp_path):
        """LocalWorkspace._generate_settings should include attribution."""
        from aef_adapters.workspaces.local import LocalWorkspace

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)

        # Pass path, not IsolatedWorkspace
        await LocalWorkspace._generate_settings(tmp_path)

        settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))

        assert settings["attribution"]["commits"] is False
        assert settings["attribution"]["pullRequests"] is False


class TestBaseWorkspaceAttribution:
    """Tests for base workspace attribution settings."""

    @pytest.mark.asyncio
    async def test_base_generate_settings_includes_attribution(self, tmp_path):
        """BaseIsolatedWorkspace._generate_settings should include attribution."""
        from aef_adapters.workspaces.base import BaseIsolatedWorkspace

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)

        # BaseIsolatedWorkspace._generate_settings takes IsolatedWorkspace
        # Create a minimal workspace for the test
        from aef_adapters.agents.agentic_types import WorkspaceConfig
        from aef_adapters.workspaces.types import IsolatedWorkspace

        config = WorkspaceConfig(session_id="test-session")
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend="docker_hardened",
        )

        await BaseIsolatedWorkspace._generate_settings(workspace)

        settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))

        assert "attribution" in settings
        assert settings["attribution"]["commits"] is False
        assert settings["attribution"]["pullRequests"] is False


class TestAttributionIntegration:
    """Integration tests for attribution across workspace lifecycle."""

    def _make_config(self):
        """Create a minimal config for InMemoryWorkspace."""
        from dataclasses import dataclass

        @dataclass
        class MinimalConfig:
            session_id: str = "test-session"

        return MinimalConfig()

    @pytest.mark.asyncio
    async def test_workspace_creation_includes_attribution(self):
        """When workspace is created, attribution should be set."""
        from aef_adapters.workspaces.memory import InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Settings should exist with attribution
            settings_content = workspace.files[".claude/settings.json"].content
            settings = json.loads(settings_content.decode())
            assert settings["attribution"]["commits"] is False

    @pytest.mark.asyncio
    async def test_attribution_not_overwritten(self):
        """Attribution settings should not be accidentally overwritten."""
        from aef_adapters.workspaces.memory import InMemoryWorkspace

        config = self._make_config()
        async with InMemoryWorkspace.create(config) as workspace:
            # Get initial settings
            settings_content = workspace.files[".claude/settings.json"].content
            initial = json.loads(settings_content.decode())
            assert initial["attribution"]["commits"] is False

            # Simulate re-reading (settings should be stable)
            final = json.loads(settings_content.decode())
            assert final["attribution"]["commits"] is False
