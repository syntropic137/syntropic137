"""Tests for git identity injection.

See ADR-021: Isolated Workspace Architecture - Git Identity section.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from aef_adapters.workspaces.git import (
    ExecutionContext,
    GitInjector,
    build_commit_message,
    get_git_injector,
)
from aef_shared.settings.workspace import GitIdentitySettings


class TestBuildCommitMessage:
    """Test build_commit_message function."""

    def test_simple_message(self) -> None:
        """Simple message without context."""
        result = build_commit_message("Fix bug")
        assert result.startswith("Fix bug")
        assert "Applied by AEF agent" in result

    def test_with_full_context(self) -> None:
        """Message with full execution context."""
        context = ExecutionContext(
            workflow_id="workflow-123",
            execution_id="exec-abc",
            session_id="session-xyz",
            initiated_by_name="John Doe",
            initiated_by_email="john@example.com",
        )

        result = build_commit_message("Add feature", context)

        assert result.startswith("Add feature")
        assert "Applied by AEF agent" in result
        assert "Workflow: workflow-123" in result
        assert "Execution: exec-abc" in result
        assert "Session: session-xyz" in result
        assert "Co-authored-by: John Doe <john@example.com>" in result

    def test_with_partial_context(self) -> None:
        """Message with partial context."""
        context = ExecutionContext(
            workflow_id="workflow-123",
            # Missing execution_id, session_id, initiated_by
        )

        result = build_commit_message("Update", context)

        assert "Workflow: workflow-123" in result
        assert "Execution:" not in result
        assert "Co-authored-by:" not in result


class TestGitInjector:
    """Test GitInjector class."""

    @pytest.fixture
    def mock_workspace(self) -> AsyncMock:
        """Create a mock workspace."""
        return AsyncMock()

    @pytest.fixture
    def successful_executor(self) -> AsyncMock:
        """Create an executor that always succeeds."""

        async def executor(_workspace, _cmd):
            return (0, "", "")

        return AsyncMock(side_effect=executor)

    @pytest.fixture
    def failing_executor(self) -> AsyncMock:
        """Create an executor that always fails."""

        async def executor(_workspace, _cmd):
            return (1, "", "git config failed")

        return AsyncMock(side_effect=executor)

    @pytest.mark.asyncio
    async def test_inject_identity_success(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should inject git identity successfully."""
        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
        }

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(mock_workspace, successful_executor)

            assert result is True
            # Should have called executor at least twice (user.name, user.email)
            assert successful_executor.call_count >= 2

    @pytest.mark.asyncio
    async def test_inject_identity_with_override(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should use workflow override when provided."""
        # Set different env values
        env = {
            "AEF_GIT_USER_NAME": "env-user",
            "AEF_GIT_USER_EMAIL": "env@example.com",
        }

        override = GitIdentitySettings(
            user_name="override-user",
            user_email="override@example.com",
        )

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(
                mock_workspace,
                successful_executor,
                workflow_override=override,
            )

            assert result is True
            # Check that override values were used (in command calls)
            calls = successful_executor.call_args_list
            # Find the user.name call
            name_call = next(
                (c for c in calls if "user.name" in str(c)),
                None,
            )
            assert name_call is not None
            assert "override-user" in str(name_call)

    @pytest.mark.asyncio
    async def test_inject_identity_no_config(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should return False when no identity configured."""
        env = {"APP_ENVIRONMENT": "production"}  # Production, no dev fallback

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(mock_workspace, successful_executor)

            assert result is False
            # Should not have called executor
            successful_executor.assert_not_called()

    @pytest.mark.asyncio
    async def test_inject_identity_command_fails(
        self,
        mock_workspace: AsyncMock,
        failing_executor: AsyncMock,
    ) -> None:
        """Should return False when git config fails."""
        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
        }

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(mock_workspace, failing_executor)

            assert result is False

    @pytest.mark.asyncio
    async def test_inject_https_credentials(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should inject HTTPS credentials when token provided."""
        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
            "AEF_GIT_TOKEN": "ghp_test123token",
        }

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(mock_workspace, successful_executor)

            assert result is True
            # Should have called executor for credentials
            calls = [str(c) for c in successful_executor.call_args_list]
            # Check for credential.helper call
            assert any("credential.helper" in c for c in calls)


class TestExecutionContext:
    """Test ExecutionContext dataclass."""

    def test_defaults(self) -> None:
        """All fields should default to None."""
        ctx = ExecutionContext()

        assert ctx.workflow_id is None
        assert ctx.execution_id is None
        assert ctx.session_id is None
        assert ctx.initiated_by_name is None
        assert ctx.initiated_by_email is None

    def test_with_values(self) -> None:
        """Should store provided values."""
        ctx = ExecutionContext(
            workflow_id="wf",
            execution_id="ex",
            session_id="ses",
            initiated_by_name="Name",
            initiated_by_email="email@test.com",
        )

        assert ctx.workflow_id == "wf"
        assert ctx.initiated_by_email == "email@test.com"


class TestGetGitInjector:
    """Test get_git_injector singleton."""

    def test_returns_injector(self) -> None:
        """Should return a GitInjector instance."""
        injector = get_git_injector()
        assert isinstance(injector, GitInjector)

    def test_singleton(self) -> None:
        """Should return same instance on repeated calls."""
        injector1 = get_git_injector()
        injector2 = get_git_injector()
        assert injector1 is injector2


class TestGitInjectorWithTokenVending:
    """Test GitInjector with token vending service integration."""

    @pytest.fixture
    def mock_workspace(self) -> AsyncMock:
        """Create a mock workspace."""
        return AsyncMock()

    @pytest.fixture
    def successful_executor(self) -> AsyncMock:
        """Create an executor that always succeeds."""

        async def executor(_workspace, _cmd):
            return (0, "", "")

        return AsyncMock(side_effect=executor)

    @pytest.mark.asyncio
    async def test_inject_with_execution_id(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should accept execution_id parameter."""
        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
        }

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(
                mock_workspace,
                successful_executor,
                execution_id="test-exec-123",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_inject_with_token_vending_service(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should accept token_vending_service parameter."""
        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
        }

        # Mock token vending service
        mock_tvs = AsyncMock()
        mock_tvs.vend_github_token = AsyncMock(return_value="test-token")

        with patch.dict(os.environ, env, clear=True):
            injector = GitInjector()
            result = await injector.inject_identity(
                mock_workspace,
                successful_executor,
                execution_id="test-exec-123",
                token_vending_service=mock_tvs,
            )

            # Should succeed (token vending not used for basic identity)
            assert result is True
