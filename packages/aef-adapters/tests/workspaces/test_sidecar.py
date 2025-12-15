"""Tests for sidecar proxy manager."""

from __future__ import annotations

from unittest import mock

import pytest

from aef_adapters.workspaces.sidecar import (
    SidecarConfig,
    SidecarInstance,
    SidecarManager,
    get_sidecar_manager,
    reset_sidecar_manager,
)


class TestSidecarConfig:
    """Tests for SidecarConfig."""

    def test_defaults(self) -> None:
        """Should have sensible defaults."""
        config = SidecarConfig(execution_id="exec-123")

        assert config.execution_id == "exec-123"
        assert config.tenant_id is None
        assert config.port == 8081
        assert "api.anthropic.com" in config.allowed_hosts
        assert config.memory_limit == "128m"

    def test_with_tenant(self) -> None:
        """Should accept tenant_id."""
        config = SidecarConfig(
            execution_id="exec-123",
            tenant_id="tenant-abc",
        )

        assert config.tenant_id == "tenant-abc"


class TestSidecarInstance:
    """Tests for SidecarInstance."""

    def test_proxy_properties(self) -> None:
        """Should provide proxy URLs."""
        config = SidecarConfig(execution_id="exec-123")
        instance = SidecarInstance(
            container_id="abc123",
            container_name="aef-sidecar-exec-123",
            config=config,
            network_name="aef-net-exec-123",
            proxy_url="http://aef-sidecar-exec-123:8081",
        )

        assert instance.http_proxy == "http://aef-sidecar-exec-123:8081"
        assert instance.https_proxy == "http://aef-sidecar-exec-123:8081"


class TestSidecarManager:
    """Tests for SidecarManager."""

    def test_init(self) -> None:
        """Should initialize with defaults."""
        manager = SidecarManager()

        assert manager._default_image == "aef-sidecar:latest"
        assert len(manager._active_sidecars) == 0

    def test_init_custom_image(self) -> None:
        """Should accept custom image."""
        manager = SidecarManager(image="custom-sidecar:v1")

        assert manager._default_image == "custom-sidecar:v1"

    @pytest.mark.asyncio
    async def test_create_mocked(self) -> None:
        """Should create sidecar with Docker commands (mocked)."""
        manager = SidecarManager()
        config = SidecarConfig(
            execution_id="exec-test-123",
            tenant_id="tenant-test",
        )

        # Mock asyncio.create_subprocess_exec
        mock_process = mock.AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = mock.AsyncMock(return_value=(b"container-id-abc123\n", b""))

        # Need to mock multiple subprocess calls
        call_count = 0

        async def mock_subprocess(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            proc = mock.AsyncMock()
            cmd = args[0] if args else ""

            if "network" in str(cmd) and "inspect" in str(args):
                # Network doesn't exist
                proc.returncode = 1
                proc.wait = mock.AsyncMock()
            elif "network" in str(cmd) and "create" in str(args):
                # Create network succeeds
                proc.returncode = 0
                proc.communicate = mock.AsyncMock(return_value=(b"", b""))
            elif cmd == "docker" and "run" in args:
                # Run container
                proc.returncode = 0
                proc.communicate = mock.AsyncMock(return_value=(b"abc123\n", b""))
            elif "inspect" in str(args) and "Health" in str(args):
                # Health check
                proc.returncode = 0
                proc.communicate = mock.AsyncMock(return_value=(b"healthy\n", b""))
            else:
                proc.returncode = 0
                proc.communicate = mock.AsyncMock(return_value=(b"", b""))
                proc.wait = mock.AsyncMock()

            return proc

        with mock.patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_subprocess,
        ):
            instance = await manager.create(config)

            assert instance.container_id == "abc123"
            assert "sidecar" in instance.container_name
            assert instance.config == config
            assert ":8081" in instance.proxy_url

    @pytest.mark.asyncio
    async def test_destroy_mocked(self) -> None:
        """Should destroy sidecar (mocked)."""
        manager = SidecarManager()
        config = SidecarConfig(execution_id="exec-123")
        instance = SidecarInstance(
            container_id="abc123",
            container_name="aef-sidecar-test",
            config=config,
            network_name="aef-net-test",
            proxy_url="http://sidecar:8081",
        )

        # Add to active sidecars
        manager._active_sidecars["aef-sidecar-test"] = instance

        mock_process = mock.AsyncMock()
        mock_process.returncode = 0
        mock_process.wait = mock.AsyncMock()

        with mock.patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            await manager.destroy(instance)

            assert "aef-sidecar-test" not in manager._active_sidecars


class TestSidecarSingleton:
    """Tests for singleton functions."""

    def test_get_sidecar_manager(self) -> None:
        """Should return singleton."""
        reset_sidecar_manager()

        manager1 = get_sidecar_manager()
        manager2 = get_sidecar_manager()

        assert manager1 is manager2

    def test_reset_sidecar_manager(self) -> None:
        """Should reset singleton."""
        manager1 = get_sidecar_manager()
        reset_sidecar_manager()
        manager2 = get_sidecar_manager()

        assert manager1 is not manager2
