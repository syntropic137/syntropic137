"""ADR Compliance Tests.

These tests verify that implementation matches ADR requirements.
They require Docker running and aef-workspace-claude:latest built.

Run with:
    pytest tests/integration/test_adr_compliance.py -v

Prerequisites:
    just workspace-build

ADRs verified:
    - ADR-021: Isolated Workspace Architecture
    - ADR-023: Workspace-First Execution Model
"""

from __future__ import annotations

import pytest

# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


class TestADR021IsolatedWorkspaceArchitecture:
    """Verify ADR-021: Isolated Workspace Architecture requirements."""

    async def test_gvisor_backend_available(self) -> None:
        """ADR-021: gVisor backend should be available when Docker is installed."""
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        # On systems with Docker and runsc, this should return True
        # On systems without, it should return False (not raise)
        result = GVisorWorkspace.is_available()
        assert isinstance(result, bool)

    async def test_hardened_docker_backend_available(self) -> None:
        """ADR-021: Hardened Docker backend should be available when Docker is."""
        from aef_adapters.workspaces.docker_hardened import HardenedDockerWorkspace

        result = HardenedDockerWorkspace.is_available()
        assert isinstance(result, bool)

    async def test_workspace_router_fails_without_backend_in_prod(self) -> None:
        """ADR-021/023: Router must fail in prod if no backend available."""
        import os
        from unittest.mock import patch

        from aef_adapters.workspaces.router import WorkspaceRouter

        router = WorkspaceRouter()

        # Mock all backends as unavailable
        with patch.object(router, "get_available_backends", return_value=[]):
            with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}):
                with pytest.raises(RuntimeError, match="No isolation backend available"):
                    router.get_best_backend()


class TestADR023WorkspaceFirstExecution:
    """Verify ADR-023: Workspace-First Execution Model requirements."""

    @pytest.fixture
    async def workspace_config(self) -> "IsolatedWorkspaceConfig":
        """Create a workspace config for testing."""
        from aef_adapters.agents.agentic_types import WorkspaceConfig
        from aef_adapters.workspaces.types import IsolatedWorkspaceConfig

        return IsolatedWorkspaceConfig(
            base_config=WorkspaceConfig(
                session_id="test-adr-compliance",
                workflow_id="test-workflow",
                phase_id="test-phase",
            ),
            execution_id="test-execution-adr-compliance",
        )

    @pytest.fixture
    async def workspace(
        self, workspace_config: "IsolatedWorkspaceConfig"
    ) -> "IsolatedWorkspace":
        """Create a real workspace for testing.

        This requires:
        - Docker running
        - aef-workspace-claude:latest built (just workspace-build)
        - gVisor or HardenedDocker backend available
        """
        from aef_adapters.workspaces import get_workspace_router
        from aef_adapters.workspaces.gvisor import GVisorWorkspace
        from aef_adapters.workspaces.docker_hardened import HardenedDockerWorkspace

        router = get_workspace_router()

        # Skip if no container backends available (needs real containers)
        if not GVisorWorkspace.is_available() and not HardenedDockerWorkspace.is_available():
            pytest.skip("No container backends available (gVisor or HardenedDocker required)")

        async with router.create(workspace_config) as ws:
            # Skip if workspace doesn't have a container_id (using local fallback)
            if not ws.container_id:
                pytest.skip("Workspace is using local fallback, not container")
            yield ws

    async def test_container_has_agent_runner(
        self, workspace: "IsolatedWorkspace"
    ) -> None:
        """ADR-023: aef_agent_runner MUST be installed in container."""
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        code, stdout, stderr = await GVisorWorkspace.execute_command(
            workspace, ["python", "-c", "import aef_agent_runner; print('OK')"]
        )
        assert code == 0, f"aef_agent_runner not installed: {stderr}"
        assert "OK" in stdout

    async def test_container_has_claude_sdk(
        self, workspace: "IsolatedWorkspace"
    ) -> None:
        """ADR-023: claude_agent_sdk MUST be installed in container."""
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        code, stdout, stderr = await GVisorWorkspace.execute_command(
            workspace, ["python", "-c", "import claude_agent_sdk; print('OK')"]
        )
        assert code == 0, f"claude_agent_sdk not installed: {stderr}"
        assert "OK" in stdout

    async def test_container_has_anthropic_sdk(
        self, workspace: "IsolatedWorkspace"
    ) -> None:
        """ADR-023: anthropic SDK MUST be installed in container."""
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        code, stdout, stderr = await GVisorWorkspace.execute_command(
            workspace, ["python", "-c", "import anthropic; print('OK')"]
        )
        assert code == 0, f"anthropic not installed: {stderr}"
        assert "OK" in stdout

    async def test_container_has_gh_cli(self, workspace: "IsolatedWorkspace") -> None:
        """ADR-021: gh CLI MUST be available for PR creation."""
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        code, stdout, stderr = await GVisorWorkspace.execute_command(
            workspace, ["gh", "--version"]
        )
        assert code == 0, f"gh CLI not installed: {stderr}"
        assert "gh version" in stdout

    async def test_container_has_git(self, workspace: "IsolatedWorkspace") -> None:
        """ADR-021: git MUST be available for repository operations."""
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        code, stdout, stderr = await GVisorWorkspace.execute_command(
            workspace, ["git", "--version"]
        )
        assert code == 0, f"git not installed: {stderr}"
        assert "git version" in stdout

    async def test_git_command_available(
        self, workspace: "IsolatedWorkspace"
    ) -> None:
        """ADR-021: Git command MUST be available in workspace.

        The full git configuration (identity, credentials) depends on
        environment settings and is tested separately. Here we just
        verify the git binary is available.
        """
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        # Check git is installed and accessible
        code, stdout, stderr = await GVisorWorkspace.execute_command(
            workspace, ["git", "--version"]
        )
        assert code == 0, f"Git not available: {stderr}"
        assert "git version" in stdout

    async def test_workspace_directories_exist(
        self, workspace: "IsolatedWorkspace"
    ) -> None:
        """ADR-021: Standard workspace directories MUST exist.

        Note: The container mounts a local directory over /workspace,
        so we check for directories created by the router, not the image.
        """
        from aef_adapters.workspaces.gvisor import GVisorWorkspace

        # Check /workspace exists and is writable
        code, _, stderr = await GVisorWorkspace.execute_command(
            workspace, ["test", "-d", "/workspace"]
        )
        assert code == 0, f"/workspace directory missing: {stderr}"

        # Check /workspace/.context exists (created by router)
        code, _, stderr = await GVisorWorkspace.execute_command(
            workspace, ["test", "-d", "/workspace/.context"]
        )
        assert code == 0, f"/workspace/.context directory missing: {stderr}"

        # Check /workspace/artifacts exists (created by router)
        code, _, stderr = await GVisorWorkspace.execute_command(
            workspace, ["test", "-d", "/workspace/artifacts"]
        )
        assert code == 0, f"/workspace/artifacts directory missing: {stderr}"

        # Check /workspace is writable
        code, _, stderr = await GVisorWorkspace.execute_command(
            workspace, ["touch", "/workspace/.write-test"]
        )
        assert code == 0, f"/workspace is not writable: {stderr}"


class TestAgentContainerContract:
    """Verify AgentContainerContract validation works correctly."""

    async def test_validates_correct_image(self) -> None:
        """Contract should pass for aef-workspace-claude:latest."""
        from aef_adapters.workspaces.contract import AgentContainerContract

        result = await AgentContainerContract.validate_image(
            "aef-workspace-claude:latest"
        )
        assert result.passed, f"Validation failed: {result.failures}"

    async def test_rejects_wrong_image(self) -> None:
        """Contract should fail for python:3.12-slim (missing components)."""
        from aef_adapters.workspaces.contract import AgentContainerContract

        result = await AgentContainerContract.validate_image("python:3.12-slim")
        assert not result.passed
        assert "Missing command: git" in result.failures
        assert "Missing command: gh" in result.failures
        assert "Missing Python module: aef_agent_runner" in result.failures
