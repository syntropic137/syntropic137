"""Tests for AgenticIsolationAdapter error surfacing (P0-2 regression)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.agentic.adapter import (
    AgenticIsolationAdapter,
    WorkspaceProvisionError,
)


@pytest.mark.asyncio
async def test_provision_failure_surfaces_real_message() -> None:
    """Underlying docker error must propagate as WorkspaceProvisionError with context.

    Regression: previously the error became a generic "Unknown error" by the time
    it reached `syn execution show`, leaving users unable to diagnose Docker
    socket-proxy denials (P0-2).
    """
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    adapter = AgenticIsolationAdapter()

    mock_provider = MagicMock()
    mock_provider.create = AsyncMock(
        side_effect=RuntimeError(
            "Failed to create container: docker: Error response from daemon: "
            "network agent-net not found"
        )
    )

    config = IsolationConfig(
        execution_id="exec-abc",
        workspace_id="ws-xyz",
        image="test:latest",
        environment={},
    )

    with (
        patch.object(adapter, "_provider", mock_provider),
        pytest.raises(WorkspaceProvisionError) as exc_info,
    ):
        await adapter.create(config)

    msg = str(exc_info.value)
    assert "exec-abc" in msg
    assert "network agent-net not found" in msg
    # And the original exception is chained so logs preserve the cause
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_provision_success_does_not_raise() -> None:
    """Happy path is unaffected by the error-wrap."""
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    adapter = AgenticIsolationAdapter()

    mock_workspace = MagicMock()
    mock_workspace.id = "ws-123"
    mock_workspace.metadata = {"workspace_dir": "/tmp/x"}

    mock_provider = MagicMock()
    mock_provider.create = AsyncMock(return_value=mock_workspace)

    config = IsolationConfig(
        execution_id="exec-abc",
        workspace_id="ws-xyz",
        image="test:latest",
        environment={},
    )

    with patch.object(adapter, "_provider", mock_provider):
        handle = await adapter.create(config)

    assert handle.isolation_id == "ws-123"
    assert handle.isolation_type == "docker"
