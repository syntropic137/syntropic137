"""Tests for workspace environment enforcement (ADR-023).

These tests verify that:
1. LocalWorkspace fails in non-test environments
2. InMemoryWorkspace fails in non-test environments
3. WorkspaceRouter fails in non-test environments when no backend available
4. All workspaces work correctly in test environments

See ADR-023: Workspace-First Execution Model
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from aef_adapters.workspaces.local import (
    NonIsolatedWorkspaceError,
    _assert_test_environment,
)
from aef_adapters.workspaces.memory import (
    InMemoryWorkspace,
    TestEnvironmentRequiredError,
)
from aef_adapters.workspaces.memory import (
    _assert_test_environment as memory_assert_test_environment,
)


class TestLocalWorkspaceEnforcement:
    """Tests for LocalWorkspace environment enforcement."""

    def test_fails_in_development_environment(self) -> None:
        """LocalWorkspace should fail in development environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            with pytest.raises(NonIsolatedWorkspaceError) as exc_info:
                _assert_test_environment()

            assert "development" in str(exc_info.value)
            assert "WorkspaceRouter" in str(exc_info.value)
            assert "ADR-023" in str(exc_info.value)

    def test_fails_in_production_environment(self) -> None:
        """LocalWorkspace should fail in production environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}):
            with pytest.raises(NonIsolatedWorkspaceError) as exc_info:
                _assert_test_environment()

            assert "production" in str(exc_info.value)

    def test_fails_in_staging_environment(self) -> None:
        """LocalWorkspace should fail in staging environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "staging"}):
            with pytest.raises(NonIsolatedWorkspaceError) as exc_info:
                _assert_test_environment()

            assert "staging" in str(exc_info.value)

    def test_succeeds_in_test_environment(self) -> None:
        """LocalWorkspace should succeed in test environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            # Should not raise
            _assert_test_environment()

    def test_succeeds_in_testing_environment(self) -> None:
        """LocalWorkspace should succeed in testing environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "testing"}):
            # Should not raise
            _assert_test_environment()

    def test_error_message_is_helpful(self) -> None:
        """Error message should explain how to fix the issue."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            with pytest.raises(NonIsolatedWorkspaceError) as exc_info:
                _assert_test_environment()

            error_msg = str(exc_info.value)
            # Should mention the alternative
            assert "WorkspaceRouter" in error_msg
            # Should mention the ADRs
            assert "ADR-023" in error_msg
            assert "ADR-021" in error_msg


class TestInMemoryWorkspaceEnforcement:
    """Tests for InMemoryWorkspace environment enforcement."""

    def test_fails_in_development_environment(self) -> None:
        """InMemoryWorkspace should fail in development environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            with pytest.raises(TestEnvironmentRequiredError) as exc_info:
                memory_assert_test_environment()

            assert "development" in str(exc_info.value)
            assert "WorkspaceRouter" in str(exc_info.value)

    def test_fails_in_production_environment(self) -> None:
        """InMemoryWorkspace should fail in production environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}):
            with pytest.raises(TestEnvironmentRequiredError) as exc_info:
                memory_assert_test_environment()

            assert "production" in str(exc_info.value)

    def test_succeeds_in_test_environment(self) -> None:
        """InMemoryWorkspace should succeed in test environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            # Should not raise
            memory_assert_test_environment()

    def test_is_available_returns_true_in_test(self) -> None:
        """is_available should return True in test environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            assert InMemoryWorkspace.is_available() is True

    def test_is_available_returns_false_in_dev(self) -> None:
        """is_available should return False in development environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            assert InMemoryWorkspace.is_available() is False


class TestWorkspaceRouterEnforcement:
    """Tests for WorkspaceRouter environment enforcement."""

    def test_get_best_backend_fails_in_dev_when_no_backends(self) -> None:
        """WorkspaceRouter.get_best_backend should fail in dev with no backends."""
        from aef_adapters.workspaces.router import WorkspaceRouter

        router = WorkspaceRouter()

        # Mock no backends available
        with (
            patch.object(router, "get_available_backends", return_value=[]),
            patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                router.get_best_backend()

            error_msg = str(exc_info.value)
            assert "ADR-023" in error_msg
            assert "Docker" in error_msg

    def test_get_best_backend_returns_none_in_test_when_no_backends(self) -> None:
        """WorkspaceRouter.get_best_backend should return None in test with no backends."""
        from aef_adapters.workspaces.router import WorkspaceRouter

        router = WorkspaceRouter()

        # Mock no backends available
        with (
            patch.object(router, "get_available_backends", return_value=[]),
            patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}),
        ):
            result = router.get_best_backend()
            assert result is None

    def test_is_test_environment_detection(self) -> None:
        """WorkspaceRouter should correctly detect test environment."""
        from aef_adapters.workspaces.router import WorkspaceRouter

        router = WorkspaceRouter()

        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            assert router._is_test_environment() is True

        with patch.dict(os.environ, {"APP_ENVIRONMENT": "testing"}):
            assert router._is_test_environment() is True

        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            assert router._is_test_environment() is False

        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}):
            assert router._is_test_environment() is False


@pytest.mark.asyncio
class TestInMemoryWorkspaceIntegration:
    """Integration tests for InMemoryWorkspace."""

    async def test_create_and_use_workspace(self) -> None:
        """Test creating and using InMemoryWorkspace in test environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            from dataclasses import dataclass

            @dataclass
            class MockConfig:
                session_id: str = "test-session"

            async with InMemoryWorkspace.create(MockConfig()) as workspace:
                # Should be able to write and read files
                await workspace.write_file("test.txt", b"hello world")
                content = await workspace.read_file("test.txt")
                assert content == b"hello world"

                # Should track files
                assert await workspace.file_exists("test.txt")
                assert not await workspace.file_exists("nonexistent.txt")

    async def test_artifact_collection(self) -> None:
        """Test artifact collection from InMemoryWorkspace."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            from dataclasses import dataclass

            @dataclass
            class MockConfig:
                session_id: str = "test-session"

            async with InMemoryWorkspace.create(MockConfig()) as workspace:
                # Write some artifacts
                await workspace.write_file("output/result.txt", b"result data")
                await workspace.write_file("output/report.json", b'{"status": "ok"}')

                # Collect artifacts
                artifacts = await InMemoryWorkspace.collect_artifacts(workspace)

                # Should have our 2 artifacts + the .gitkeep from setup
                assert len(artifacts) >= 2
                paths = [str(p) for p, _ in artifacts]
                assert "result.txt" in paths
                assert "report.json" in paths
