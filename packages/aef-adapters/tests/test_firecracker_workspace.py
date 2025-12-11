"""Tests for FirecrackerWorkspace.

These tests verify the Firecracker MicroVM workspace implementation.
Most tests are unit tests since Firecracker requires Linux with KVM.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from aef_adapters.workspaces import FirecrackerWorkspace
from aef_adapters.workspaces.base import BaseIsolatedWorkspace
from aef_shared.settings import IsolationBackend, WorkspaceSecuritySettings

if TYPE_CHECKING:
    from pathlib import Path


class TestFirecrackerWorkspaceClass:
    """Tests for FirecrackerWorkspace class attributes."""

    def test_isolation_backend(self) -> None:
        """FirecrackerWorkspace should have FIRECRACKER backend."""
        assert FirecrackerWorkspace.isolation_backend == IsolationBackend.FIRECRACKER

    def test_inherits_from_base(self) -> None:
        """FirecrackerWorkspace should inherit from BaseIsolatedWorkspace."""
        assert issubclass(FirecrackerWorkspace, BaseIsolatedWorkspace)

    def test_has_default_paths(self) -> None:
        """Should have default paths for kernel, rootfs, and sockets."""
        assert hasattr(FirecrackerWorkspace, "DEFAULT_KERNEL_PATH")
        assert hasattr(FirecrackerWorkspace, "DEFAULT_ROOTFS_PATH")
        assert hasattr(FirecrackerWorkspace, "DEFAULT_SOCKET_DIR")


class TestIsAvailable:
    """Tests for is_available() method."""

    @patch("sys.platform", "darwin")
    def test_returns_false_on_macos(self) -> None:
        """Should return False on macOS (no KVM)."""
        assert FirecrackerWorkspace.is_available() is False

    @patch("sys.platform", "win32")
    def test_returns_false_on_windows(self) -> None:
        """Should return False on Windows (no KVM)."""
        assert FirecrackerWorkspace.is_available() is False

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_returns_false_when_no_kvm(self, mock_which: MagicMock) -> None:
        """Should return False when /dev/kvm doesn't exist."""
        mock_which.return_value = "/usr/bin/firecracker"

        with patch("pathlib.Path.exists", return_value=False):
            assert FirecrackerWorkspace.is_available() is False

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_returns_false_when_no_firecracker(self, mock_which: MagicMock) -> None:
        """Should return False when firecracker binary not found."""
        mock_which.return_value = None

        with patch("pathlib.Path.exists", return_value=True):
            assert FirecrackerWorkspace.is_available() is False

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_returns_true_when_all_available(self, mock_which: MagicMock) -> None:
        """Should return True when all requirements are met."""
        mock_which.return_value = "/usr/bin/firecracker"

        # Mock all path checks to return True
        with patch("pathlib.Path.exists", return_value=True):
            assert FirecrackerWorkspace.is_available() is True


class TestBuildFirecrackerConfig:
    """Tests for _build_firecracker_config() method."""

    @pytest.fixture
    def security(self) -> WorkspaceSecuritySettings:
        """Create default security settings."""
        return WorkspaceSecuritySettings(_env_file=None)

    def test_includes_boot_source(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Config should include boot source with kernel path."""
        config = FirecrackerWorkspace._build_firecracker_config(
            vm_id="test-vm",
            workspace_dir=tmp_path,
            security=security,
        )
        assert "boot-source" in config
        assert "kernel_image_path" in config["boot-source"]
        assert "boot_args" in config["boot-source"]

    def test_includes_rootfs_drive(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Config should include rootfs drive."""
        config = FirecrackerWorkspace._build_firecracker_config(
            vm_id="test-vm",
            workspace_dir=tmp_path,
            security=security,
        )
        assert "drives" in config
        assert len(config["drives"]) > 0
        assert config["drives"][0]["drive_id"] == "rootfs"
        assert config["drives"][0]["is_root_device"] is True

    def test_includes_machine_config(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Config should include machine configuration."""
        config = FirecrackerWorkspace._build_firecracker_config(
            vm_id="test-vm",
            workspace_dir=tmp_path,
            security=security,
        )
        assert "machine-config" in config
        assert "vcpu_count" in config["machine-config"]
        assert "mem_size_mib" in config["machine-config"]
        assert config["machine-config"]["smt"] is False  # Security

    def test_network_disabled_by_default(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Network interfaces should be empty when network disabled."""
        assert security.allow_network is False

        config = FirecrackerWorkspace._build_firecracker_config(
            vm_id="test-vm",
            workspace_dir=tmp_path,
            security=security,
        )
        assert config["network-interfaces"] == []

    def test_includes_vsock(self, security: WorkspaceSecuritySettings, tmp_path: Path) -> None:
        """Config should include vsock for host-guest communication."""
        config = FirecrackerWorkspace._build_firecracker_config(
            vm_id="test-vm",
            workspace_dir=tmp_path,
            security=security,
        )
        assert "vsock" in config
        assert "guest_cid" in config["vsock"]
        assert "uds_path" in config["vsock"]

    def test_respects_memory_limit(self, tmp_path: Path) -> None:
        """Config should use memory limit from security settings."""
        security = WorkspaceSecuritySettings(_env_file=None)
        # Default is 512Mi

        config = FirecrackerWorkspace._build_firecracker_config(
            vm_id="test-vm",
            workspace_dir=tmp_path,
            security=security,
        )
        assert config["machine-config"]["mem_size_mib"] == 512


class TestParseMemoryToMb:
    """Tests for _parse_memory_to_mb() helper."""

    @pytest.mark.parametrize(
        "mem_str,expected",
        [
            ("512Mi", 512),
            ("512MB", 512),
            ("1Gi", 1024),
            ("1GB", 1024),
            ("2G", 2048),
            ("256M", 256),
            ("1024", 1024),
        ],
    )
    def test_parses_memory_formats(self, mem_str: str, expected: int) -> None:
        """Should parse various memory format strings to MB."""
        result = FirecrackerWorkspace._parse_memory_to_mb(mem_str)
        assert result == expected

    def test_returns_default_for_invalid(self) -> None:
        """Should return default 512 for invalid input."""
        result = FirecrackerWorkspace._parse_memory_to_mb("invalid")
        assert result == 512


class TestGenerateMacAddress:
    """Tests for _generate_mac_address() helper."""

    def test_generates_valid_mac(self) -> None:
        """Should generate a valid MAC address format."""
        mac = FirecrackerWorkspace._generate_mac_address("test-seed")

        # Check format: XX:XX:XX:XX:XX:XX
        parts = mac.split(":")
        assert len(parts) == 6
        for part in parts:
            assert len(part) == 2
            int(part, 16)  # Should be valid hex

    def test_locally_administered(self) -> None:
        """MAC should be locally administered (first byte = 06)."""
        mac = FirecrackerWorkspace._generate_mac_address("test-seed")
        assert mac.startswith("06:")

    def test_deterministic(self) -> None:
        """Same seed should produce same MAC."""
        mac1 = FirecrackerWorkspace._generate_mac_address("same-seed")
        mac2 = FirecrackerWorkspace._generate_mac_address("same-seed")
        assert mac1 == mac2

    def test_different_seeds_different_macs(self) -> None:
        """Different seeds should produce different MACs."""
        mac1 = FirecrackerWorkspace._generate_mac_address("seed-1")
        mac2 = FirecrackerWorkspace._generate_mac_address("seed-2")
        assert mac1 != mac2


class TestInheritedFunctionality:
    """Tests to verify inherited functionality from BaseIsolatedWorkspace."""

    def test_inherits_inject_context(self) -> None:
        """Should inherit inject_context from BaseIsolatedWorkspace."""
        assert hasattr(FirecrackerWorkspace, "inject_context")
        assert (
            FirecrackerWorkspace.inject_context.__func__
            is BaseIsolatedWorkspace.inject_context.__func__
        )

    def test_inherits_collect_artifacts(self) -> None:
        """Should inherit collect_artifacts from BaseIsolatedWorkspace."""
        assert hasattr(FirecrackerWorkspace, "collect_artifacts")
        assert (
            FirecrackerWorkspace.collect_artifacts.__func__
            is BaseIsolatedWorkspace.collect_artifacts.__func__
        )

    def test_inherits_setup_hooks(self) -> None:
        """Should inherit _setup_hooks from BaseIsolatedWorkspace."""
        assert hasattr(FirecrackerWorkspace, "_setup_hooks")

    def test_inherits_setup_directories(self) -> None:
        """Should inherit _setup_directories from BaseIsolatedWorkspace."""
        assert hasattr(FirecrackerWorkspace, "_setup_directories")
