"""Tests for environment variable injection.

See ADR-021: Isolated Workspace Architecture.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from aef_adapters.workspaces.env_injector import (
    EnvInjector,
    InjectedEnvVar,
    get_env_injector,
)


class TestInjectedEnvVar:
    """Test InjectedEnvVar dataclass."""

    def test_defaults(self) -> None:
        """Should have sensible defaults."""
        env_var = InjectedEnvVar(name="TEST", value="value")

        assert env_var.name == "TEST"
        assert env_var.value == "value"
        assert env_var.required is False
        assert env_var.description == ""

    def test_with_all_fields(self) -> None:
        """Should accept all fields."""
        env_var = InjectedEnvVar(
            name="API_KEY",
            value="secret",
            required=True,
            description="API key for testing",
        )

        assert env_var.required is True
        assert env_var.description == "API key for testing"


class TestEnvInjector:
    """Test EnvInjector class."""

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

    def test_get_required_env_vars_no_keys(self) -> None:
        """Should return empty list when no API keys configured."""
        env = {}
        with patch.dict(os.environ, env, clear=True):
            injector = EnvInjector()
            env_vars = injector.get_required_env_vars()

            assert len(env_vars) == 0

    def test_get_required_env_vars_with_anthropic(self) -> None:
        """Should include Anthropic key from environment."""
        env = {"ANTHROPIC_API_KEY": "sk-ant-test123"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = None
            mock_settings.return_value.openai_api_key = None

            injector = EnvInjector()
            env_vars = injector.get_required_env_vars()

            assert len(env_vars) == 1
            assert env_vars[0].name == "ANTHROPIC_API_KEY"
            assert env_vars[0].value == "sk-ant-test123"

    def test_get_docker_env_args(self) -> None:
        """Should return Docker --env arguments."""
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "OPENAI_API_KEY": "sk-openai-test",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = None
            mock_settings.return_value.openai_api_key = None

            injector = EnvInjector()
            args = injector.get_docker_env_args()

            assert "--env" in args
            assert "ANTHROPIC_API_KEY=sk-ant-test" in args
            assert "OPENAI_API_KEY=sk-openai-test" in args

    @pytest.mark.asyncio
    async def test_inject_api_keys_success(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should inject API keys successfully."""
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = None
            mock_settings.return_value.openai_api_key = None

            injector = EnvInjector()
            result = await injector.inject_api_keys(mock_workspace, successful_executor)

            assert result is True
            assert successful_executor.call_count >= 1

    @pytest.mark.asyncio
    async def test_inject_api_keys_no_keys(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should return True when no API keys configured."""
        env = {}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = None
            mock_settings.return_value.openai_api_key = None

            injector = EnvInjector()
            result = await injector.inject_api_keys(mock_workspace, successful_executor)

            assert result is True
            # Should not have called executor (nothing to inject)
            successful_executor.assert_not_called()

    @pytest.mark.asyncio
    async def test_inject_api_keys_require_anthropic_missing(
        self,
        mock_workspace: AsyncMock,
        successful_executor: AsyncMock,
    ) -> None:
        """Should raise ValueError when Anthropic key required but missing."""
        env = {}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = None
            mock_settings.return_value.openai_api_key = None

            injector = EnvInjector()
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
                await injector.inject_api_keys(
                    mock_workspace,
                    successful_executor,
                    require_anthropic=True,
                )


class TestGetEnvInjector:
    """Test get_env_injector singleton."""

    def test_returns_injector(self) -> None:
        """Should return an EnvInjector instance."""
        injector = get_env_injector()
        assert isinstance(injector, EnvInjector)

    def test_singleton(self) -> None:
        """Should return same instance on repeated calls."""
        injector1 = get_env_injector()
        injector2 = get_env_injector()
        assert injector1 is injector2
