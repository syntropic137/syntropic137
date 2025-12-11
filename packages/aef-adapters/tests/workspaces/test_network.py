"""Tests for network allowlist enforcement.

See ADR-021: Isolated Workspace Architecture - Network Allowlist.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from aef_adapters.workspaces.network import (
    DEFAULT_ALLOWED_HOSTS,
    EgressProxy,
    NetworkConfig,
    get_egress_proxy,
)


class TestNetworkConfig:
    """Test NetworkConfig class."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        config = NetworkConfig()

        assert config.allow_network is True
        assert config.use_proxy is True
        assert len(config.allowed_hosts) > 0
        assert "api.anthropic.com" in config.allowed_hosts

    def test_custom_allowed_hosts(self) -> None:
        """Should accept custom allowed hosts."""
        config = NetworkConfig(allowed_hosts=["custom.api.com", "other.api.com"])

        assert config.allowed_hosts == ["custom.api.com", "other.api.com"]

    def test_get_proxy_url(self) -> None:
        """Should return correct proxy URL."""
        config = NetworkConfig(proxy_host="proxy.local", proxy_port=9090)

        assert config.get_proxy_url() == "http://proxy.local:9090"

    def test_get_env_vars_with_proxy(self) -> None:
        """Should return proxy environment variables."""
        config = NetworkConfig(allow_network=True, use_proxy=True, proxy_port=8080)

        env_vars = config.get_env_vars()

        assert "HTTP_PROXY" in env_vars
        assert "HTTPS_PROXY" in env_vars
        assert "http_proxy" in env_vars
        assert "https_proxy" in env_vars
        assert "8080" in env_vars["HTTP_PROXY"]

    def test_get_env_vars_no_network(self) -> None:
        """Should return empty env vars when network disabled."""
        config = NetworkConfig(allow_network=False)

        env_vars = config.get_env_vars()

        assert env_vars == {}

    def test_get_env_vars_no_proxy(self) -> None:
        """Should return empty env vars when proxy disabled."""
        config = NetworkConfig(allow_network=True, use_proxy=False)

        env_vars = config.get_env_vars()

        assert env_vars == {}

    def test_from_settings(self) -> None:
        """Should create config from settings."""
        env = {
            "AEF_SECURITY_ALLOW_NETWORK": "true",
            "AEF_SECURITY_ALLOWED_HOSTS": "custom.api.com,other.api.com",
        }

        with patch.dict(os.environ, env, clear=True):
            config = NetworkConfig.from_settings()

            assert config.allow_network is True
            assert "custom.api.com" in config.allowed_hosts


class TestDefaultAllowedHosts:
    """Test default allowed hosts list."""

    def test_includes_llm_apis(self) -> None:
        """Should include LLM API endpoints."""
        assert "api.anthropic.com" in DEFAULT_ALLOWED_HOSTS
        assert "api.openai.com" in DEFAULT_ALLOWED_HOSTS

    def test_includes_github(self) -> None:
        """Should include GitHub."""
        assert "github.com" in DEFAULT_ALLOWED_HOSTS
        assert "api.github.com" in DEFAULT_ALLOWED_HOSTS

    def test_includes_package_repos(self) -> None:
        """Should include package repositories."""
        assert "pypi.org" in DEFAULT_ALLOWED_HOSTS
        assert "files.pythonhosted.org" in DEFAULT_ALLOWED_HOSTS


class TestEgressProxy:
    """Test EgressProxy class."""

    def test_default_port(self) -> None:
        """Should use default port."""
        proxy = EgressProxy()

        assert proxy.port == 8080

    def test_custom_allowed_hosts(self) -> None:
        """Should accept custom allowed hosts."""
        proxy = EgressProxy(allowed_hosts=["custom.com"])

        assert proxy.allowed_hosts == ["custom.com"]

    def test_is_running_initially_false(self) -> None:
        """Should not be running initially."""
        proxy = EgressProxy()

        assert proxy.is_running is False

    def test_get_docker_network_args_not_running(self) -> None:
        """Should return empty args when not running."""
        proxy = EgressProxy()

        args = proxy.get_docker_network_args()

        assert args == []

    @pytest.mark.asyncio
    async def test_is_container_running_false(self) -> None:
        """Should detect container not running."""
        proxy = EgressProxy()

        # Mock subprocess to return empty (no container)
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_proc

            result = await proxy._is_container_running()

            assert result is False


class TestGetEgressProxy:
    """Test get_egress_proxy singleton."""

    def test_returns_proxy(self) -> None:
        """Should return an EgressProxy instance."""
        proxy = get_egress_proxy()

        assert isinstance(proxy, EgressProxy)

    def test_singleton(self) -> None:
        """Should return same instance on repeated calls."""
        proxy1 = get_egress_proxy()
        proxy2 = get_egress_proxy()

        assert proxy1 is proxy2
