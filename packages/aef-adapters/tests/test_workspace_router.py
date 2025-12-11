"""Tests for WorkspaceRouter.

These tests verify the workspace router selects and manages
isolation backends correctly.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aef_adapters.workspaces import (
    E2BWorkspace,
    FirecrackerWorkspace,
    GVisorWorkspace,
    HardenedDockerWorkspace,
    RouterStats,
    WorkspaceRouter,
    get_workspace_router,
    reset_workspace_router,
)
from aef_shared.settings import IsolationBackend


class TestRouterStats:
    """Tests for RouterStats dataclass."""

    def test_default_values(self) -> None:
        """RouterStats should have sensible defaults."""
        stats = RouterStats()
        assert stats.total_created == 0
        assert stats.active_count == 0
        assert stats.overflow_count == 0
        assert stats.failed_count == 0
        assert stats.by_backend == {}


class TestWorkspaceRouterClass:
    """Tests for WorkspaceRouter class."""

    def test_has_backend_priority(self) -> None:
        """Should define backend priority order."""
        assert hasattr(WorkspaceRouter, "BACKEND_PRIORITY")
        assert len(WorkspaceRouter.BACKEND_PRIORITY) > 0
        # Firecracker should be highest priority
        assert WorkspaceRouter.BACKEND_PRIORITY[0] == IsolationBackend.FIRECRACKER

    def test_has_backend_classes(self) -> None:
        """Should map backends to implementation classes."""
        assert hasattr(WorkspaceRouter, "BACKEND_CLASSES")
        assert IsolationBackend.FIRECRACKER in WorkspaceRouter.BACKEND_CLASSES
        assert IsolationBackend.GVISOR in WorkspaceRouter.BACKEND_CLASSES
        assert IsolationBackend.DOCKER_HARDENED in WorkspaceRouter.BACKEND_CLASSES
        assert IsolationBackend.CLOUD in WorkspaceRouter.BACKEND_CLASSES


class TestGetAvailableBackends:
    """Tests for get_available_backends() method."""

    def test_checks_each_backend(self) -> None:
        """Should check is_available for each backend."""
        router = WorkspaceRouter()

        # Mock all backends as unavailable
        with (
            patch.object(FirecrackerWorkspace, "is_available", return_value=False),
            patch.object(GVisorWorkspace, "is_available", return_value=False),
            patch.object(HardenedDockerWorkspace, "is_available", return_value=False),
            patch.object(E2BWorkspace, "is_available", return_value=False),
        ):
            available = router.get_available_backends()
            assert available == []

    def test_returns_available_backends(self) -> None:
        """Should return list of available backends."""
        router = WorkspaceRouter()

        with (
            patch.object(FirecrackerWorkspace, "is_available", return_value=False),
            patch.object(GVisorWorkspace, "is_available", return_value=True),
            patch.object(HardenedDockerWorkspace, "is_available", return_value=True),
            patch.object(E2BWorkspace, "is_available", return_value=False),
        ):
            available = router.get_available_backends()
            assert IsolationBackend.GVISOR in available
            assert IsolationBackend.DOCKER_HARDENED in available
            assert IsolationBackend.FIRECRACKER not in available
            assert IsolationBackend.CLOUD not in available


class TestGetBestBackend:
    """Tests for get_best_backend() method."""

    def test_returns_highest_priority_available(self) -> None:
        """Should return highest priority available backend."""
        router = WorkspaceRouter()

        # Firecracker available = should return Firecracker
        with (
            patch.object(FirecrackerWorkspace, "is_available", return_value=True),
            patch.object(GVisorWorkspace, "is_available", return_value=True),
        ):
            best = router.get_best_backend()
            assert best == IsolationBackend.FIRECRACKER

        # Firecracker unavailable, gVisor available = should return gVisor
        with (
            patch.object(FirecrackerWorkspace, "is_available", return_value=False),
            patch.object(GVisorWorkspace, "is_available", return_value=True),
            patch.object(HardenedDockerWorkspace, "is_available", return_value=True),
        ):
            best = router.get_best_backend()
            assert best == IsolationBackend.GVISOR

    def test_raises_when_none_available(self) -> None:
        """Should raise RuntimeError when no backend available."""
        router = WorkspaceRouter()

        with (
            patch.object(FirecrackerWorkspace, "is_available", return_value=False),
            patch.object(GVisorWorkspace, "is_available", return_value=False),
            patch.object(HardenedDockerWorkspace, "is_available", return_value=False),
            patch.object(E2BWorkspace, "is_available", return_value=False),
            pytest.raises(RuntimeError, match="No isolation backend available"),
        ):
            router.get_best_backend()


class TestGetBackendClass:
    """Tests for get_backend_class() method."""

    def test_returns_correct_class(self) -> None:
        """Should return correct implementation class."""
        router = WorkspaceRouter()

        assert router.get_backend_class(IsolationBackend.FIRECRACKER) is FirecrackerWorkspace
        assert router.get_backend_class(IsolationBackend.GVISOR) is GVisorWorkspace
        assert router.get_backend_class(IsolationBackend.DOCKER_HARDENED) is HardenedDockerWorkspace
        assert router.get_backend_class(IsolationBackend.CLOUD) is E2BWorkspace

    def test_raises_for_unimplemented(self) -> None:
        """Should raise ValueError for unimplemented backends."""
        router = WorkspaceRouter()

        with pytest.raises(ValueError, match="not implemented"):
            router.get_backend_class(IsolationBackend.KATA)


class TestRouterSingleton:
    """Tests for get_workspace_router() singleton."""

    def test_returns_same_instance(self) -> None:
        """Should return same instance on repeated calls."""
        reset_workspace_router()

        router1 = get_workspace_router()
        router2 = get_workspace_router()

        assert router1 is router2

    def test_reset_clears_instance(self) -> None:
        """Should create new instance after reset."""
        reset_workspace_router()
        router1 = get_workspace_router()

        reset_workspace_router()
        router2 = get_workspace_router()

        assert router1 is not router2


class TestRouterStatsTracking:
    """Tests for router statistics tracking."""

    def test_initial_stats(self) -> None:
        """Should start with zero stats."""
        router = WorkspaceRouter()

        assert router.stats.total_created == 0
        assert router.active_count == 0

    def test_active_count(self) -> None:
        """active_count should reflect active workspaces."""
        router = WorkspaceRouter()

        assert router.active_count == 0


class TestBackendPriority:
    """Tests to verify backend priority is correct."""

    def test_firecracker_highest_priority(self) -> None:
        """Firecracker should be highest priority (strongest isolation)."""
        assert WorkspaceRouter.BACKEND_PRIORITY[0] == IsolationBackend.FIRECRACKER

    def test_cloud_lowest_priority(self) -> None:
        """Cloud should be lowest priority (overflow only)."""
        assert WorkspaceRouter.BACKEND_PRIORITY[-1] == IsolationBackend.CLOUD

    def test_gvisor_before_hardened_docker(self) -> None:
        """gVisor should be before hardened Docker (stronger isolation)."""
        gvisor_idx = WorkspaceRouter.BACKEND_PRIORITY.index(IsolationBackend.GVISOR)
        docker_idx = WorkspaceRouter.BACKEND_PRIORITY.index(IsolationBackend.DOCKER_HARDENED)
        assert gvisor_idx < docker_idx
