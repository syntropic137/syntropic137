"""Tests for Docker adapters.

These tests mock subprocess calls so they can run without Docker.
For real Docker integration tests, see tests/integration/.

Run: pytest packages/aef-adapters/src/aef_adapters/workspace_backends/docker/test_docker_adapters.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aef_domain.contexts.workspaces._shared.value_objects import (
    CapabilityType,
    IsolationBackendType,
    IsolationConfig,
    IsolationHandle,
    SecurityPolicy,
    SidecarConfig,
    TokenType,
)

# =============================================================================
# MOCK HELPERS
# =============================================================================


def create_mock_process(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    """Create a mock subprocess."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.communicate = AsyncMock(return_value=(stdout, stderr))
    mock_proc.wait = AsyncMock(return_value=returncode)
    mock_proc.kill = MagicMock()
    return mock_proc


def create_subprocess_mock_factory():
    """Create a mock factory that handles multiple subprocess calls.

    Returns different responses based on the command:
    - docker run: returns container ID
    - docker inspect: returns "true" (running)
    - docker stop/rm: returns success
    - docker network: returns success
    - docker exec: returns command output
    """
    call_count = {"count": 0}

    async def mock_create_subprocess_exec(*args, **kwargs):
        call_count["count"] += 1
        cmd = " ".join(str(a) for a in args)

        # docker run -> return container ID
        if "docker" in cmd and "run" in cmd:
            return create_mock_process(returncode=0, stdout=b"mockcontainer123")

        # docker inspect -> return true (running)
        if "docker" in cmd and "inspect" in cmd:
            if "NetworkSettings" in cmd:
                return create_mock_process(returncode=0, stdout=b"aef-workspace-net")
            return create_mock_process(returncode=0, stdout=b"true")

        # docker network -> success
        if "docker" in cmd and "network" in cmd:
            return create_mock_process(returncode=0)

        # docker stop/rm -> success
        if "docker" in cmd and ("stop" in cmd or "rm" in cmd):
            return create_mock_process(returncode=0)

        # docker exec -> return output
        if "docker" in cmd and "exec" in cmd:
            return create_mock_process(returncode=0, stdout=b"Hello, World!\n")

        # Default
        return create_mock_process(returncode=0)

    return mock_create_subprocess_exec


# =============================================================================
# DOCKER ISOLATION ADAPTER TESTS
# =============================================================================


@pytest.mark.integration
class TestDockerIsolationAdapter:
    """Tests for DockerIsolationAdapter."""

    @pytest.fixture
    def config(self) -> IsolationConfig:
        """Create test config."""
        return IsolationConfig(
            execution_id="exec-test-123",
            workspace_id="ws-test-456",
            workflow_id="wf-test-789",
            backend=IsolationBackendType.DOCKER_HARDENED,
            capabilities=(CapabilityType.NETWORK,),
            security_policy=SecurityPolicy(memory_limit_mb=512, cpu_limit_cores=1.0),
        )

    @pytest.mark.asyncio
    async def test_create_returns_handle(self, config: IsolationConfig) -> None:
        """Test that create returns a valid IsolationHandle."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_mock_factory()):
            adapter = DockerIsolationAdapter(use_gvisor=False)
            handle = await adapter.create(config)

            assert handle.isolation_id == "mockcontainer123"
            assert handle.isolation_type == "docker"
            assert handle.workspace_path == "/workspace"

    @pytest.mark.asyncio
    async def test_create_with_gvisor(self, config: IsolationConfig) -> None:
        """Test container creation with gVisor runtime."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        with patch(
            "asyncio.create_subprocess_exec", side_effect=create_subprocess_mock_factory()
        ) as mock_exec:
            adapter = DockerIsolationAdapter(use_gvisor=True)
            handle = await adapter.create(config)

            assert handle.isolation_type == "gvisor"

            # Verify --runtime=runsc was in the command (check all calls)
            all_calls = str(mock_exec.call_args_list)
            assert "--runtime=runsc" in all_calls

    @pytest.mark.asyncio
    async def test_create_failure_raises(self, config: IsolationConfig) -> None:
        """Test that creation failure raises RuntimeError."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        async def failing_subprocess(*args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            if "docker" in cmd and "run" in cmd:
                return create_mock_process(returncode=1, stderr=b"Error: image not found")
            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=failing_subprocess):
            adapter = DockerIsolationAdapter(use_gvisor=False)

            with pytest.raises(RuntimeError, match="Failed to create container"):
                await adapter.create(config)

    @pytest.mark.asyncio
    async def test_destroy_removes_container(self, config: IsolationConfig) -> None:
        """Test that destroy stops and removes the container."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        with patch(
            "asyncio.create_subprocess_exec", side_effect=create_subprocess_mock_factory()
        ) as mock_exec:
            adapter = DockerIsolationAdapter(use_gvisor=False)
            handle = await adapter.create(config)

            await adapter.destroy(handle)

            # Verify docker stop and rm were called
            all_calls = str(mock_exec.call_args_list)
            assert "stop" in all_calls
            assert "rm" in all_calls

    @pytest.mark.asyncio
    async def test_execute_returns_result(self, config: IsolationConfig) -> None:
        """Test command execution returns ExecutionResult."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_mock_factory()):
            adapter = DockerIsolationAdapter(use_gvisor=False)
            handle = await adapter.create(config)

            result = await adapter.execute(handle, ["echo", "Hello, World!"])

            assert result.exit_code == 0
            assert result.success is True
            assert "Hello, World!" in result.stdout
            assert result.stdout_lines >= 1

    @pytest.mark.asyncio
    async def test_execute_captures_failure(self, config: IsolationConfig) -> None:
        """Test that failed commands are captured correctly."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        async def mock_subprocess(*args, **kwargs):
            # args[0] is first arg (docker), args[1] is second arg (command)
            if len(args) >= 2:
                first_arg = str(args[0])
                second_arg = str(args[1])
                full_cmd = " ".join(str(a) for a in args)

                # docker exec fails
                if first_arg == "docker" and second_arg == "exec":
                    return create_mock_process(returncode=1, stderr=b"command not found")
                # docker run succeeds
                if first_arg == "docker" and second_arg == "run":
                    return create_mock_process(returncode=0, stdout=b"mockcontainer123")
                # docker inspect (for health check and network)
                if first_arg == "docker" and second_arg == "inspect":
                    if "NetworkSettings" in full_cmd:
                        return create_mock_process(returncode=0, stdout=b"aef-workspace-net")
                    return create_mock_process(returncode=0, stdout=b"true")
                # docker network
                if first_arg == "docker" and second_arg == "network":
                    return create_mock_process(returncode=0)
                # docker stop/rm
                if first_arg == "docker" and second_arg in ("stop", "rm"):
                    return create_mock_process(returncode=0)

            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerIsolationAdapter(use_gvisor=False)
            handle = await adapter.create(config)

            result = await adapter.execute(handle, ["nonexistent-command"])

            assert result.exit_code == 1
            assert result.success is False
            assert "not found" in result.stderr

    @pytest.mark.asyncio
    async def test_health_check_returns_true_for_running(self, config: IsolationConfig) -> None:
        """Test health_check returns True for running container."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_mock_factory()):
            adapter = DockerIsolationAdapter(use_gvisor=False)
            handle = await adapter.create(config)

            is_healthy = await adapter.health_check(handle)

            assert is_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_for_stopped(self, config: IsolationConfig) -> None:
        """Test health_check returns False for stopped container."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        health_check_count = {"count": 0}

        async def mock_subprocess(*args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            # For health check after container is "stopped"
            if "docker" in cmd and "inspect" in cmd and ".State.Running" in cmd:
                health_check_count["count"] += 1
                # First call (during create) returns true, later calls return false
                if health_check_count["count"] <= 1:
                    return create_mock_process(returncode=0, stdout=b"true")
                return create_mock_process(returncode=0, stdout=b"false")
            if "docker" in cmd and "run" in cmd:
                return create_mock_process(returncode=0, stdout=b"mockcontainer123")
            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerIsolationAdapter(use_gvisor=False)
            handle = await adapter.create(config)

            # Second health check should return false (simulating stopped container)
            is_healthy = await adapter.health_check(handle)

            assert is_healthy is False

    def test_is_available_checks_docker(self) -> None:
        """Test is_available checks for docker command."""
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/docker"
            assert DockerIsolationAdapter.is_available() is True

            mock_which.return_value = None
            assert DockerIsolationAdapter.is_available() is False


# =============================================================================
# DOCKER SIDECAR ADAPTER TESTS
# =============================================================================


class TestDockerSidecarAdapter:
    """Tests for DockerSidecarAdapter."""

    @pytest.fixture
    def sidecar_config(self) -> SidecarConfig:
        """Create test sidecar config."""
        return SidecarConfig(
            workspace_id="ws-test-456",
            listen_port=8080,
            allowed_hosts=("api.anthropic.com", "api.github.com"),
        )

    @pytest.fixture
    def isolation_handle(self) -> IsolationHandle:
        """Create test isolation handle."""
        return IsolationHandle(
            isolation_id="container123",
            isolation_type="docker",
            workspace_path="/workspace",
            host_workspace_path="/tmp/aef-workspace-test",
        )

    @pytest.mark.asyncio
    async def test_start_returns_handle(
        self,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that start returns a valid SidecarHandle."""
        from aef_adapters.workspace_backends.docker import DockerSidecarAdapter

        async def mock_subprocess(*args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            if "docker" in cmd and "run" in cmd:
                return create_mock_process(returncode=0, stdout=b"sidecar123")
            if "docker" in cmd and "inspect" in cmd:
                if "NetworkSettings" in cmd:
                    return create_mock_process(returncode=0, stdout=b"aef-workspace-net")
                return create_mock_process(returncode=0, stdout=b"true")
            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerSidecarAdapter()
            handle = await adapter.start(sidecar_config, isolation_handle)

            assert handle.sidecar_id == "sidecar123"
            assert "8080" in handle.proxy_url
            assert handle.started_at is not None

    @pytest.mark.asyncio
    async def test_stop_removes_container(
        self,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that stop removes the sidecar container."""
        from aef_adapters.workspace_backends.docker import DockerSidecarAdapter

        async def mock_subprocess(*args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            if "docker" in cmd and "run" in cmd:
                return create_mock_process(returncode=0, stdout=b"sidecar123")
            if "docker" in cmd and "inspect" in cmd:
                if "NetworkSettings" in cmd:
                    return create_mock_process(returncode=0, stdout=b"aef-workspace-net")
                return create_mock_process(returncode=0, stdout=b"true")
            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess) as mock_exec:
            adapter = DockerSidecarAdapter()
            handle = await adapter.start(sidecar_config, isolation_handle)

            await adapter.stop(handle)

            # Verify docker stop was called
            all_calls = str(mock_exec.call_args_list)
            assert "stop" in all_calls

    @pytest.mark.asyncio
    async def test_configure_tokens(
        self,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test token configuration."""
        from aef_adapters.workspace_backends.docker import DockerSidecarAdapter

        async def mock_subprocess(*args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            if "docker" in cmd and "run" in cmd:
                return create_mock_process(returncode=0, stdout=b"sidecar123")
            if "docker" in cmd and "inspect" in cmd:
                if "NetworkSettings" in cmd:
                    return create_mock_process(returncode=0, stdout=b"aef-workspace-net")
                return create_mock_process(returncode=0, stdout=b"true")
            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerSidecarAdapter()
            handle = await adapter.start(sidecar_config, isolation_handle)

            # Should not raise
            await adapter.configure_tokens(
                handle,
                {TokenType.ANTHROPIC: "sk-ant-xxx", TokenType.GITHUB: "ghp_xxx"},
                ttl_seconds=300,
            )

    @pytest.mark.asyncio
    async def test_health_check(
        self,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test health check returns correct status."""
        from aef_adapters.workspace_backends.docker import DockerSidecarAdapter

        async def mock_subprocess(*args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            if "docker" in cmd and "run" in cmd:
                return create_mock_process(returncode=0, stdout=b"sidecar123")
            if "docker" in cmd and "inspect" in cmd:
                if "NetworkSettings" in cmd:
                    return create_mock_process(returncode=0, stdout=b"aef-workspace-net")
                return create_mock_process(returncode=0, stdout=b"true")
            return create_mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerSidecarAdapter()
            handle = await adapter.start(sidecar_config, isolation_handle)

            assert await adapter.health_check(handle) is True


# =============================================================================
# INTEGRATION TEST: Docker Adapters Together
# =============================================================================


# =============================================================================
# DOCKER EVENT STREAM ADAPTER TESTS
# =============================================================================


class TestDockerEventStreamAdapter:
    """Tests for DockerEventStreamAdapter."""

    @pytest.fixture
    def isolation_handle(self) -> IsolationHandle:
        """Create test isolation handle."""
        return IsolationHandle(
            isolation_id="container-stream-123",
            isolation_type="docker",
            workspace_path="/workspace",
            host_workspace_path="/tmp/aef-workspace-stream-test",
        )

    @pytest.mark.asyncio
    async def test_stream_yields_lines(self, isolation_handle: IsolationHandle) -> None:
        """Test that stream yields stdout lines."""
        from aef_adapters.workspace_backends.docker import DockerEventStreamAdapter

        # Mock process that outputs lines
        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(
            side_effect=[
                b'{"event": "start"}\n',
                b'{"event": "progress"}\n',
                b'{"event": "done"}\n',
                b"",  # EOF
            ]
        )

        mock_proc = MagicMock()
        mock_proc.stdout = mock_stdout
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.returncode = 0
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()

        async def mock_subprocess(*args, **kwargs):
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerEventStreamAdapter()

            lines = []
            async for line in adapter.stream(
                isolation_handle,
                ["python", "-u", "agent.py"],
            ):
                lines.append(line)

            assert len(lines) == 3
            assert '{"event": "start"}' in lines[0]
            assert '{"event": "done"}' in lines[2]

    @pytest.mark.asyncio
    async def test_stream_handles_timeout(self, isolation_handle: IsolationHandle) -> None:
        """Test that stream handles timeout correctly."""
        from aef_adapters.workspace_backends.docker import DockerEventStreamAdapter

        # Mock process that blocks
        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(side_effect=TimeoutError())

        mock_proc = MagicMock()
        mock_proc.stdout = mock_stdout
        mock_proc.stderr = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.kill = MagicMock()

        async def mock_subprocess(*args, **kwargs):
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            adapter = DockerEventStreamAdapter()

            lines = []
            async for line in adapter.stream(
                isolation_handle,
                ["python", "slow.py"],
                timeout_seconds=1,
            ):
                lines.append(line)

            # Should complete without error, just empty
            assert len(lines) == 0
            # Process should be terminated
            mock_proc.terminate.assert_called_once()


class TestDockerAdaptersIntegration:
    """Integration tests for Docker adapters working together (mocked)."""

    @pytest.mark.asyncio
    async def test_workspace_with_sidecar_lifecycle(self) -> None:
        """Test full lifecycle: isolation + sidecar."""
        from aef_adapters.workspace_backends.docker import (
            DockerIsolationAdapter,
            DockerSidecarAdapter,
        )

        config = IsolationConfig(
            execution_id="exec-integration",
            workspace_id="ws-integration",
            backend=IsolationBackendType.DOCKER_HARDENED,
        )

        sidecar_config = SidecarConfig(
            workspace_id="ws-integration",
            listen_port=8080,
        )

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_mock_factory()):
            # Create isolation
            isolation_adapter = DockerIsolationAdapter(use_gvisor=False)
            isolation_handle = await isolation_adapter.create(config)

            # Start sidecar
            sidecar_adapter = DockerSidecarAdapter()
            sidecar_handle = await sidecar_adapter.start(sidecar_config, isolation_handle)

            # Configure tokens
            await sidecar_adapter.configure_tokens(
                sidecar_handle,
                {TokenType.ANTHROPIC: "sk-ant-xxx"},
                ttl_seconds=300,
            )

            # Execute command
            result = await isolation_adapter.execute(
                isolation_handle,
                ["echo", "Hello from workspace!"],
            )

            assert result.success is True

            # Stop sidecar
            await sidecar_adapter.stop(sidecar_handle)

            # Destroy isolation
            await isolation_adapter.destroy(isolation_handle)
