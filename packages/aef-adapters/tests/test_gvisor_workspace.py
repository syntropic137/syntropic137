"""Tests for GVisorWorkspace.

These tests verify the gVisor Docker workspace implementation.
Most tests are unit tests that mock Docker commands.
Integration tests require Docker with runsc runtime.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import GVisorWorkspace, IsolatedWorkspaceConfig
from aef_adapters.workspaces.types import IsolatedWorkspace
from aef_shared.settings import IsolationBackend, WorkspaceSecuritySettings


class TestGVisorWorkspaceClass:
    """Tests for GVisorWorkspace class attributes."""

    def test_isolation_backend(self) -> None:
        """GVisorWorkspace should have GVISOR backend."""
        assert GVisorWorkspace.isolation_backend == IsolationBackend.GVISOR

    def test_inherits_from_base(self) -> None:
        """GVisorWorkspace should inherit from BaseIsolatedWorkspace."""
        from aef_adapters.workspaces.base import BaseIsolatedWorkspace

        assert issubclass(GVisorWorkspace, BaseIsolatedWorkspace)


class TestIsAvailable:
    """Tests for is_available() method."""

    @patch("shutil.which")
    def test_returns_false_when_docker_not_installed(self, mock_which: MagicMock) -> None:
        """Should return False when Docker is not installed."""
        mock_which.return_value = None
        assert GVisorWorkspace.is_available() is False

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_returns_true_when_runsc_in_runtimes(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        """Should return True when runsc is in Docker runtimes."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"runsc": {}}',
        )
        assert GVisorWorkspace.is_available() is True

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_returns_true_when_gvisor_in_runtimes(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        """Should return True when gvisor is in Docker runtimes."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"gvisor": {}}',
        )
        assert GVisorWorkspace.is_available() is True

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_falls_back_to_runsc_binary_check(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        """Should check for runsc binary if Docker info fails."""
        mock_which.side_effect = ["/usr/bin/docker", "/usr/bin/runsc"]
        mock_run.return_value = MagicMock(
            returncode=1,  # Docker info failed
            stdout="",
        )
        assert GVisorWorkspace.is_available() is True


class TestBuildDockerCommand:
    """Tests for _build_docker_command() method."""

    @pytest.fixture
    def security(self) -> WorkspaceSecuritySettings:
        """Create default security settings."""
        return WorkspaceSecuritySettings(_env_file=None)

    def test_includes_runtime_runsc(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include --runtime runsc."""
        cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        assert "--runtime" in cmd
        assert "runsc" in cmd

    def test_includes_network_none_by_default(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include --network none for isolation."""
        cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        assert "--network" in cmd
        idx = cmd.index("--network")
        assert cmd[idx + 1] == "none"

    def test_includes_resource_limits(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include resource limits from security settings."""
        cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        # Check memory limit
        assert "--memory" in cmd
        assert security.max_memory in cmd

        # Check CPU limit
        assert "--cpus" in cmd
        assert str(security.max_cpu) in cmd

        # Check pids limit
        assert "--pids-limit" in cmd
        assert str(security.max_pids) in cmd

    def test_includes_read_only_with_tmpfs(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include --read-only and tmpfs mounts."""
        assert security.read_only_root is True  # Default is True

        cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        assert "--read-only" in cmd
        assert "--tmpfs" in cmd

    def test_includes_security_options(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include security hardening options."""
        cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        # Drop all capabilities
        assert "--cap-drop=ALL" in cmd
        # No new privileges
        assert "--security-opt=no-new-privileges:true" in cmd

    def test_includes_workspace_mount(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should mount workspace directory."""
        cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        assert "--mount" in cmd
        # Check mount includes source and target
        mount_idx = cmd.index("--mount")
        mount_arg = cmd[mount_idx + 1]
        assert str(tmp_path) in mount_arg
        assert "/workspace" in mount_arg


class TestExecuteCommand:
    """Tests for execute_command() method."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> IsolatedWorkspace:
        """Create a mock workspace."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        ws = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="test-container-123",
        )
        ws.mark_started()
        return ws

    @pytest.mark.asyncio
    async def test_executes_docker_exec(self, workspace: IsolatedWorkspace) -> None:
        """Should use docker exec to run commands."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"output", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            exit_code, stdout, stderr = await GVisorWorkspace.execute_command(
                workspace, ["echo", "hello"]
            )

            assert exit_code == 0
            assert stdout == "output"
            assert stderr == ""

            # Verify docker exec was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert "docker" in call_args
            assert "exec" in call_args
            assert workspace.container_id in call_args
            assert "echo" in call_args
            assert "hello" in call_args

    @pytest.mark.asyncio
    async def test_handles_timeout(self, workspace: IsolatedWorkspace) -> None:
        """Should handle command timeout."""
        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            exit_code, _stdout, stderr = await GVisorWorkspace.execute_command(
                workspace, ["sleep", "100"], timeout=1
            )

            assert exit_code == -1
            assert "timed out" in stderr.lower()

    @pytest.mark.asyncio
    async def test_raises_when_no_container(self, tmp_path: Path) -> None:
        """Should raise when container_id is not set."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id=None,  # No container
        )

        with pytest.raises(RuntimeError, match="not running"):
            await GVisorWorkspace.execute_command(workspace, ["ls"])


class TestHealthCheck:
    """Tests for health_check() method."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> IsolatedWorkspace:
        """Create a mock workspace."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        ws = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="test-container-123",
        )
        ws.mark_started()
        return ws

    @pytest.mark.asyncio
    async def test_returns_false_when_not_running(self, tmp_path: Path) -> None:
        """Should return False when workspace is not running."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="test-container-123",
        )
        # Not marked as started

        result = await GVisorWorkspace.health_check(workspace)
        assert result is False

    @pytest.mark.asyncio
    async def test_checks_container_state(self, workspace: IsolatedWorkspace) -> None:
        """Should check if container is running via docker inspect."""
        # Mock docker inspect returning "true"
        inspect_proc = AsyncMock()
        inspect_proc.returncode = 0
        inspect_proc.communicate = AsyncMock(return_value=(b"true\n", b""))

        # Mock execute_command returning success
        with (
            patch("asyncio.create_subprocess_exec", return_value=inspect_proc),
            patch.object(
                GVisorWorkspace,
                "execute_command",
                return_value=(0, "", ""),
            ),
        ):
            result = await GVisorWorkspace.health_check(workspace)
            assert result is True


class TestParseMemoryString:
    """Tests for _parse_memory_string() helper."""

    @pytest.mark.parametrize(
        "mem_str,expected",
        [
            ("256MiB", 256 * 1024 * 1024),
            ("1GiB", 1024 * 1024 * 1024),
            ("512MB", 512 * 1024 * 1024),
            ("1.5GiB", int(1.5 * 1024 * 1024 * 1024)),
            ("100KB", 100 * 1024),
            ("1024B", 1024),
            ("1024", 1024),
        ],
    )
    def test_parses_memory_formats(self, mem_str: str, expected: int) -> None:
        """Should parse various memory format strings."""
        result = GVisorWorkspace._parse_memory_string(mem_str)
        assert result == expected

    def test_handles_invalid_input(self) -> None:
        """Should handle invalid input gracefully."""
        result = GVisorWorkspace._parse_memory_string("invalid")
        assert result == 0


class TestCreateIsolation:
    """Tests for _create_isolation() method."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> IsolatedWorkspaceConfig:
        """Create workspace config."""
        base = WorkspaceConfig(session_id="test-session", base_dir=tmp_path)
        return IsolatedWorkspaceConfig(base_config=base)

    @pytest.fixture
    def security(self) -> WorkspaceSecuritySettings:
        """Create security settings."""
        return WorkspaceSecuritySettings(_env_file=None)

    @pytest.mark.asyncio
    async def test_creates_container(
        self, config: IsolatedWorkspaceConfig, security: WorkspaceSecuritySettings
    ) -> None:
        """Should create Docker container with gVisor runtime."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"abc123containerid\n", b""))

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.workspace.docker_image = "test-image"
            mock_settings.return_value.workspace.docker_network = "none"

            workspace = await GVisorWorkspace._create_isolation(config, security)

            assert workspace.container_id == "abc123containerid"
            assert workspace.isolation_backend == IsolationBackend.GVISOR
            assert workspace.security is security

    @pytest.mark.asyncio
    async def test_raises_on_docker_failure(
        self, config: IsolatedWorkspaceConfig, security: WorkspaceSecuritySettings
    ) -> None:
        """Should raise RuntimeError when Docker fails."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: image not found"))

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.workspace.docker_image = "test-image"
            mock_settings.return_value.workspace.docker_network = "none"

            with pytest.raises(RuntimeError, match="Failed to create"):
                await GVisorWorkspace._create_isolation(config, security)


class TestDestroyIsolation:
    """Tests for _destroy_isolation() method."""

    @pytest.mark.asyncio
    async def test_stops_and_removes_container(self, tmp_path: Path) -> None:
        """Should stop and remove the Docker container."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="test-container",
        )

        call_count = 0
        commands_called = []

        async def mock_subprocess(*args, **_kwargs):
            nonlocal call_count
            call_count += 1
            commands_called.append(args)
            proc = AsyncMock()
            proc.wait = AsyncMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            await GVisorWorkspace._destroy_isolation(workspace)

        # Should call stop and rm
        assert call_count == 2
        assert "stop" in commands_called[0]
        assert "rm" in commands_called[1]

    @pytest.mark.asyncio
    async def test_skips_when_no_container_id(self, tmp_path: Path) -> None:
        """Should skip cleanup when container_id is None."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id=None,
        )

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            await GVisorWorkspace._destroy_isolation(workspace)
            mock_exec.assert_not_called()
