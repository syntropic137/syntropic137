"""Unit tests for InteractiveTmuxIsolationAdapter (Phase C2 seam).

These tests stub out the underlying agentic_isolation.InteractiveTmuxProvider
so they run without Docker or any host credentials.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.interactive_tmux import (
    InteractiveTmuxIsolationAdapter,
    InteractiveTmuxUnavailableError,
)
from syn_adapters.workspace_backends.interactive_tmux import adapter as adapter_mod


@pytest.mark.asyncio
async def test_create_delegates_to_provider_and_returns_handle() -> None:
    """create() forwards a WorkspaceConfig to the provider and wraps the result."""
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    fake_workspace = MagicMock()
    fake_workspace.id = "itws-abc"
    fake_workspace.metadata = {"enabled_agents": ("claude",), "workspace_dir": "/tmp/x"}
    fake_workspace._handle = MagicMock(name="InteractiveTmuxWorkspace")

    fake_provider_cls = MagicMock()
    fake_provider_instance = fake_provider_cls.return_value
    fake_provider_instance.create = AsyncMock(return_value=fake_workspace)

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", fake_provider_cls),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        adapter = InteractiveTmuxIsolationAdapter(default_image="img:tag")
        handle = await adapter.create(
            IsolationConfig(
                execution_id="exec-1",
                workspace_id="ws-1",
                image="img:tag",
                environment={"FOO": "bar"},
            )
        )

    assert handle.isolation_id == "itws-abc"
    assert handle.isolation_type == "interactive-tmux"
    assert handle.proxy_url is None
    assert handle.workspace_path == "/workspace"
    # provider_handle exposes the underlying InteractiveTmuxWorkspace driver
    assert adapter.provider_handle(handle) is fake_workspace._handle


@pytest.mark.asyncio
async def test_destroy_calls_provider_destroy_and_drops_handle() -> None:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
        IsolationHandle,
    )

    fake_workspace = MagicMock()
    fake_workspace.id = "itws-xyz"
    fake_workspace.metadata = {}
    fake_workspace._handle = MagicMock()

    fake_provider_cls = MagicMock()
    fake_provider = fake_provider_cls.return_value
    fake_provider.create = AsyncMock(return_value=fake_workspace)
    fake_provider.destroy = AsyncMock()

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", fake_provider_cls),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        adapter = InteractiveTmuxIsolationAdapter()
        await adapter.create(
            IsolationConfig(execution_id="e", workspace_id="w", image="i", environment={})
        )
        await adapter.destroy(
            IsolationHandle(
                isolation_id="itws-xyz",
                isolation_type="interactive-tmux",
                proxy_url=None,
                workspace_path="/workspace",
                host_workspace_path="",
            )
        )

    fake_provider.destroy.assert_awaited_once()
    assert "itws-xyz" not in adapter._workspaces


def test_constructor_raises_when_provider_missing() -> None:
    """Constructor MUST fail loudly when the provider class is absent.

    Silent fallback to the Docker path would hide misconfiguration —
    explicitly required by the rollout plan §6.
    """
    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", None),
        patch.object(
            adapter_mod,
            "_IMPORT_ERROR",
            "module agentic_isolation.providers.interactive_tmux not found",
        ),
        pytest.raises(InteractiveTmuxUnavailableError) as exc,
    ):
        InteractiveTmuxIsolationAdapter()
    assert "agentic-primitives" in str(exc.value)
    assert "agentprims-lab" in str(exc.value)


def test_provider_handle_returns_none_for_unknown_handle() -> None:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", MagicMock()),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        adapter = InteractiveTmuxIsolationAdapter()
        result = adapter.provider_handle(
            IsolationHandle(
                isolation_id="missing",
                isolation_type="interactive-tmux",
                proxy_url=None,
                workspace_path="/workspace",
                host_workspace_path="",
            )
        )
    assert result is None
