"""Tests for memory adapters.

Verifies:
1. Test environment enforcement (must fail outside test env)
2. Adapter functionality when in test environment
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    Artifact,
    CapabilityType,
    IsolationBackendType,
    IsolationConfig,
    SecurityPolicy,
    SidecarConfig,
    TokenType,
)
from syn_shared.settings.config import AppEnvironment, Settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syn_adapters.workspace_backends.memory import (
        MemoryArtifactAdapter,
        MemoryEventStreamAdapter,
        MemoryIsolationAdapter,
        MemorySidecarAdapter,
        MemoryTokenInjectionAdapter,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )


def _mock_settings(env: AppEnvironment) -> Settings:
    """Build a Settings object for the given environment without touching os.environ."""
    return Settings(app_environment=env)  # type: ignore[call-arg]


# =============================================================================
# TEST ENVIRONMENT ENFORCEMENT
# =============================================================================


@pytest.mark.unit
class TestEnvironmentEnforcement:
    """Tests for test environment enforcement (ADR-060)."""

    @pytest.fixture(autouse=True)
    def _reset_settings_cache(self) -> Iterator[None]:
        """Reset cached settings after each test.

        Environment enforcement tests override get_settings() which
        poisons the lru_cache. Without this cleanup, subsequent tests
        see stale settings.
        """
        yield
        from syn_shared.settings import reset_settings

        reset_settings()

    def test_memory_isolation_adapter_fails_in_development(self) -> None:
        """Test that MemoryIsolationAdapter fails in development environment."""
        from syn_adapters.in_memory import InMemoryAdapterError
        from syn_adapters.workspace_backends.memory.memory_adapter import (
            MemoryIsolationAdapter,
        )

        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.DEVELOPMENT),
            ),
            pytest.raises(InMemoryAdapterError, match="test/offline only"),
        ):
            MemoryIsolationAdapter()

    def test_memory_isolation_adapter_fails_in_production(self) -> None:
        """Test that MemoryIsolationAdapter fails in production environment."""
        from syn_adapters.in_memory import InMemoryAdapterError
        from syn_adapters.workspace_backends.memory.memory_adapter import (
            MemoryIsolationAdapter,
        )

        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.PRODUCTION),
            ),
            pytest.raises(InMemoryAdapterError),
        ):
            MemoryIsolationAdapter()

    def test_memory_sidecar_adapter_fails_outside_test(self) -> None:
        """Test that MemorySidecarAdapter fails outside test environment."""
        from syn_adapters.in_memory import InMemoryAdapterError
        from syn_adapters.workspace_backends.memory.memory_sidecar import (
            MemorySidecarAdapter,
        )

        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.STAGING),
            ),
            pytest.raises(InMemoryAdapterError),
        ):
            MemorySidecarAdapter()

    def test_memory_token_injection_adapter_fails_outside_test(self) -> None:
        """Test that MemoryTokenInjectionAdapter fails outside test environment."""
        from syn_adapters.in_memory import InMemoryAdapterError
        from syn_adapters.workspace_backends.memory.memory_token import (
            MemoryTokenInjectionAdapter,
        )

        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.DEVELOPMENT),
            ),
            pytest.raises(InMemoryAdapterError),
        ):
            MemoryTokenInjectionAdapter()

    def test_memory_artifact_adapter_fails_outside_test(self) -> None:
        """Test that MemoryArtifactAdapter fails outside test environment."""
        from syn_adapters.in_memory import InMemoryAdapterError
        from syn_adapters.workspace_backends.memory.memory_artifact import (
            MemoryArtifactAdapter,
        )

        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.DEVELOPMENT),
            ),
            pytest.raises(InMemoryAdapterError),
        ):
            MemoryArtifactAdapter()

    def test_memory_event_stream_adapter_fails_outside_test(self) -> None:
        """Test that MemoryEventStreamAdapter fails outside test environment."""
        from syn_adapters.in_memory import InMemoryAdapterError
        from syn_adapters.workspace_backends.memory.memory_stream import (
            MemoryEventStreamAdapter,
        )

        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.DEVELOPMENT),
            ),
            pytest.raises(InMemoryAdapterError),
        ):
            MemoryEventStreamAdapter()


# =============================================================================
# MEMORY ISOLATION ADAPTER TESTS
# =============================================================================


class TestMemoryIsolationAdapter:
    """Tests for MemoryIsolationAdapter functionality."""

    @pytest.fixture
    def adapter(self) -> MemoryIsolationAdapter:
        """Create adapter in test environment."""
        from syn_adapters.workspace_backends.memory import MemoryIsolationAdapter

        # Already in test environment (pytest sets APP_ENVIRONMENT=test)
        return MemoryIsolationAdapter()

    @pytest.fixture
    def config(self) -> IsolationConfig:
        """Create test config."""
        return IsolationConfig(
            execution_id="exec-123",
            workspace_id="ws-456",
            workflow_id="wf-789",
            backend=IsolationBackendType.MEMORY,
            capabilities=(CapabilityType.NETWORK, CapabilityType.GIT),
            security_policy=SecurityPolicy(memory_limit_mb=512),
        )

    @pytest.mark.asyncio
    async def test_create_returns_handle(
        self, adapter: MemoryIsolationAdapter, config: IsolationConfig
    ) -> None:
        """Test that create returns a valid handle."""
        handle = await adapter.create(config)

        assert handle.isolation_id.startswith("mem-")
        assert handle.isolation_type == "memory"
        assert handle.workspace_path == "/workspace"

    @pytest.mark.asyncio
    async def test_destroy_removes_instance(
        self, adapter: MemoryIsolationAdapter, config: IsolationConfig
    ) -> None:
        """Test that destroy removes the instance."""
        handle = await adapter.create(config)
        assert await adapter.health_check(handle) is True

        await adapter.destroy(handle)
        assert await adapter.health_check(handle) is False

    @pytest.mark.asyncio
    async def test_execute_records_command(
        self, adapter: MemoryIsolationAdapter, config: IsolationConfig
    ) -> None:
        """Test that execute records command history."""
        handle = await adapter.create(config)

        result = await adapter.execute(handle, ["echo", "hello"])

        assert result.success is True
        assert result.exit_code == 0

        history = adapter.get_command_history(handle)
        assert len(history) == 1
        assert history[0][0] == ["echo", "hello"]

    @pytest.mark.asyncio
    async def test_execute_multiple_commands(
        self, adapter: MemoryIsolationAdapter, config: IsolationConfig
    ) -> None:
        """Test multiple command execution."""
        handle = await adapter.create(config)

        await adapter.execute(handle, ["cmd1"])
        await adapter.execute(handle, ["cmd2", "arg"])
        await adapter.execute(handle, ["cmd3"])

        history = adapter.get_command_history(handle)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_health_check_returns_true_for_healthy(
        self, adapter: MemoryIsolationAdapter, config: IsolationConfig
    ) -> None:
        """Test health_check returns True for healthy instance."""
        handle = await adapter.create(config)
        assert await adapter.health_check(handle) is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_after_set_unhealthy(
        self, adapter: MemoryIsolationAdapter, config: IsolationConfig
    ) -> None:
        """Test health_check returns False after set_unhealthy."""
        handle = await adapter.create(config)
        adapter.set_unhealthy(handle)
        assert await adapter.health_check(handle) is False


# =============================================================================
# MEMORY SIDECAR ADAPTER TESTS
# =============================================================================


class TestMemorySidecarAdapter:
    """Tests for MemorySidecarAdapter functionality."""

    @pytest.fixture
    def adapter(self) -> MemorySidecarAdapter:
        """Create adapter in test environment."""
        from syn_adapters.workspace_backends.memory import MemorySidecarAdapter

        return MemorySidecarAdapter()

    @pytest.fixture
    def isolation_handle(self) -> IsolationHandle:
        """Create mock isolation handle."""
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        return IsolationHandle(
            isolation_id="mem-test123",
            isolation_type="memory",
        )

    @pytest.fixture
    def sidecar_config(self) -> SidecarConfig:
        """Create test sidecar config."""
        return SidecarConfig(
            workspace_id="ws-456",
            listen_port=8080,
        )

    @pytest.mark.asyncio
    async def test_start_returns_handle(
        self,
        adapter: MemorySidecarAdapter,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that start returns a valid handle."""
        handle = await adapter.start(sidecar_config, isolation_handle)

        assert handle.sidecar_id.startswith("sidecar-")
        assert handle.proxy_url == "http://localhost:8080"
        assert handle.started_at is not None

    @pytest.mark.asyncio
    async def test_stop_removes_sidecar(
        self,
        adapter: MemorySidecarAdapter,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that stop removes the sidecar."""
        handle = await adapter.start(sidecar_config, isolation_handle)
        assert await adapter.health_check(handle) is True

        await adapter.stop(handle)
        assert await adapter.health_check(handle) is False

    @pytest.mark.asyncio
    async def test_configure_tokens(
        self,
        adapter: MemorySidecarAdapter,
        sidecar_config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test token configuration."""
        handle = await adapter.start(sidecar_config, isolation_handle)

        await adapter.configure_tokens(
            handle,
            {TokenType.ANTHROPIC: "sk-ant-xxx", TokenType.GITHUB: "ghp_xxx"},
            ttl_seconds=600,
        )

        # No exception = success (mock doesn't expose tokens for security)


# =============================================================================
# MEMORY TOKEN INJECTION ADAPTER TESTS
# =============================================================================


class TestMemoryTokenInjectionAdapter:
    """Tests for MemoryTokenInjectionAdapter functionality."""

    @pytest.fixture
    def adapter(self) -> MemoryTokenInjectionAdapter:
        """Create adapter in test environment."""
        from syn_adapters.workspace_backends.memory import MemoryTokenInjectionAdapter

        return MemoryTokenInjectionAdapter()

    @pytest.fixture
    def isolation_handle(self) -> IsolationHandle:
        """Create mock isolation handle."""
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        return IsolationHandle(
            isolation_id="mem-test123",
            isolation_type="memory",
        )

    @pytest.mark.asyncio
    async def test_inject_returns_success(
        self,
        adapter: MemoryTokenInjectionAdapter,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that inject returns successful result."""
        result = await adapter.inject(
            isolation_handle,
            "exec-123",  # execution_id (positional due to underscore prefix)
            [TokenType.ANTHROPIC, TokenType.GITHUB],
            ttl_seconds=300,
        )

        assert result.success is True
        assert TokenType.ANTHROPIC in result.tokens_injected
        assert TokenType.GITHUB in result.tokens_injected
        assert result.ttl_seconds == 300

    @pytest.mark.asyncio
    async def test_get_injected_tokens(
        self,
        adapter: MemoryTokenInjectionAdapter,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that injected tokens can be retrieved for testing."""
        await adapter.inject(
            isolation_handle,
            "exec-123",  # execution_id (positional due to underscore prefix)
            [TokenType.ANTHROPIC],
        )

        injected = adapter.get_injected_tokens(isolation_handle)
        assert "TokenType.ANTHROPIC" in injected or "anthropic" in str(injected).lower()


# =============================================================================
# MEMORY ARTIFACT ADAPTER TESTS
# =============================================================================


class TestMemoryArtifactAdapter:
    """Tests for MemoryArtifactAdapter functionality."""

    @pytest.fixture
    def adapter(self) -> MemoryArtifactAdapter:
        """Create adapter in test environment."""
        from syn_adapters.workspace_backends.memory import MemoryArtifactAdapter

        return MemoryArtifactAdapter()

    @pytest.fixture
    def isolation_handle(self) -> IsolationHandle:
        """Create mock isolation handle."""
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        return IsolationHandle(
            isolation_id="mem-test123",
            isolation_type="memory",
        )

    @pytest.mark.asyncio
    async def test_collect_returns_empty_by_default(
        self,
        adapter: MemoryArtifactAdapter,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that collect returns empty result by default."""
        result = await adapter.collect(isolation_handle, ["*.txt"])

        assert result.success is True
        assert len(result.artifacts) == 0
        assert result.total_size_bytes == 0

    @pytest.mark.asyncio
    async def test_add_artifact_then_collect(
        self,
        adapter: MemoryArtifactAdapter,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that added artifacts are collected."""
        artifact = Artifact(
            name="output.txt",
            path="/workspace/output.txt",
            size_bytes=100,
            content_type="text/plain",
        )
        adapter.add_artifact(isolation_handle, artifact)

        result = await adapter.collect(isolation_handle, ["*"])

        assert len(result.artifacts) == 1
        assert result.artifacts[0].name == "output.txt"
        assert result.total_size_bytes == 100


# =============================================================================
# MEMORY EVENT STREAM ADAPTER TESTS
# =============================================================================


class TestMemoryEventStreamAdapter:
    """Tests for MemoryEventStreamAdapter functionality."""

    @pytest.fixture
    def adapter(self) -> MemoryEventStreamAdapter:
        """Create adapter in test environment."""
        from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter

        return MemoryEventStreamAdapter()

    @pytest.fixture
    def isolation_handle(self) -> IsolationHandle:
        """Create mock isolation handle."""
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        return IsolationHandle(
            isolation_id="mem-test123",
            isolation_type="memory",
        )

    @pytest.mark.asyncio
    async def test_stream_yields_nothing_by_default(
        self,
        adapter: MemoryEventStreamAdapter,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that stream yields nothing by default."""
        lines = [line async for line in adapter.stream(isolation_handle, ["cmd"])]
        assert lines == []

    @pytest.mark.asyncio
    async def test_stream_yields_configured_output(
        self,
        adapter: MemoryEventStreamAdapter,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that stream yields configured output."""
        adapter.set_stream_output(isolation_handle, ["line1", "line2", "line3"])

        lines = [line async for line in adapter.stream(isolation_handle, ["cmd"])]

        assert lines == ["line1", "line2", "line3"]


# Type hints imported via TYPE_CHECKING in fixtures
