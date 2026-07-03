"""Unit tests for InteractiveTmuxIsolationAdapter (Phase C2 seam).

These tests stub out the underlying agentic_isolation.InteractiveTmuxProvider
so they run without Docker or any host credentials.
"""

from __future__ import annotations

import asyncio
import time
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


async def _run_ticker(iterations: int, *, interval_s: float = 0.01) -> int:
    """Advance a counter on the event loop via `asyncio.sleep`, and return the count.

    Used as a canary: if a concurrently-running coroutine is blocking the
    event loop, this ticker starves and its final count stays low even
    though `iterations * interval_s` of wall-clock time elapsed.
    """
    ticks = 0
    for _ in range(iterations):
        await asyncio.sleep(interval_s)
        ticks += 1
    return ticks


@pytest.mark.asyncio
async def test_create_does_not_block_event_loop() -> None:
    """create() must offload the blocking provider call to a worker thread.

    `agentic_isolation.providers.interactive_tmux.InteractiveTmuxProvider.create()`
    is async-def but synchronous internally (subprocess + sleep loops up
    to ~45s) — its own docstring says callers needing concurrency must
    wrap the call in their own thread. Simulate that blocking behaviour
    with a fake provider whose create() does a real `time.sleep()`, and
    assert a concurrently-scheduled ticker keeps making progress
    throughout (issue #771 item 2).
    """
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    fake_workspace = MagicMock()
    fake_workspace.id = "itws-block-create"
    fake_workspace.metadata = {}
    fake_workspace._handle = MagicMock()

    async def blocking_create(_config: object) -> MagicMock:
        time.sleep(0.3)  # simulates the provider's synchronous subprocess/sleep work
        return fake_workspace

    fake_provider_cls = MagicMock()
    fake_provider_cls.return_value.create = blocking_create

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", fake_provider_cls),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        adapter = InteractiveTmuxIsolationAdapter()
        ticker_task = asyncio.ensure_future(_run_ticker(30))
        await adapter.create(
            IsolationConfig(execution_id="e", workspace_id="w", image="i", environment={})
        )
        ticks = await ticker_task

    # 30 x 10ms ticks should complete uninterrupted while create() blocks
    # for 300ms in its own thread. If create() blocked this event loop
    # instead, the ticker would have made near-zero progress by the time
    # create() returned.
    assert ticks > 10


@pytest.mark.asyncio
async def test_destroy_does_not_block_event_loop() -> None:
    """destroy() must also offload its blocking provider call (issue #771 item 2)."""
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
        IsolationHandle,
    )

    fake_workspace = MagicMock()
    fake_workspace.id = "itws-block-destroy"
    fake_workspace.metadata = {}
    fake_workspace._handle = MagicMock()

    async def blocking_destroy(_workspace: object) -> None:
        time.sleep(0.3)  # simulates the provider's synchronous stop() call

    fake_provider_cls = MagicMock()
    fake_provider_cls.return_value.create = AsyncMock(return_value=fake_workspace)
    fake_provider_cls.return_value.destroy = blocking_destroy

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", fake_provider_cls),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        adapter = InteractiveTmuxIsolationAdapter()
        await adapter.create(
            IsolationConfig(execution_id="e", workspace_id="w", image="i", environment={})
        )
        ticker_task = asyncio.ensure_future(_run_ticker(30))
        await adapter.destroy(
            IsolationHandle(
                isolation_id="itws-block-destroy",
                isolation_type="interactive-tmux",
                proxy_url=None,
                workspace_path="/workspace",
                host_workspace_path="",
            )
        )
        ticks = await ticker_task

    assert ticks > 10


@pytest.mark.asyncio
async def test_destroy_failure_retains_handle_for_retry() -> None:
    """A failed provider destroy MUST NOT drop the workspace handle.

    Losing the handle would make the leaked tmux/Docker resources
    unrecoverable; keeping it allows cleanup_workspace (or an operator)
    to retry the destroy.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
        IsolationHandle,
    )

    fake_workspace = MagicMock()
    fake_workspace.id = "itws-fail"
    fake_workspace.metadata = {}
    fake_workspace._handle = MagicMock()

    fake_provider_cls = MagicMock()
    fake_provider = fake_provider_cls.return_value
    fake_provider.create = AsyncMock(return_value=fake_workspace)
    fake_provider.destroy = AsyncMock(side_effect=RuntimeError("docker rm timed out"))

    handle = IsolationHandle(
        isolation_id="itws-fail",
        isolation_type="interactive-tmux",
        proxy_url=None,
        workspace_path="/workspace",
        host_workspace_path="",
    )

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", fake_provider_cls),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        adapter = InteractiveTmuxIsolationAdapter()
        await adapter.create(
            IsolationConfig(execution_id="e", workspace_id="w", image="i", environment={})
        )
        with pytest.raises(RuntimeError, match="docker rm timed out"):
            await adapter.destroy(handle)

        # Handle survives the failure: a retry can still reach the workspace.
        assert "itws-fail" in adapter._workspaces

        # Retry succeeds once the provider recovers; handle is dropped.
        fake_provider.destroy = AsyncMock()
        await adapter.destroy(handle)

    assert "itws-fail" not in adapter._workspaces


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
