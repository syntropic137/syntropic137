"""Regression tests for the production non-interactive stream adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.agentic.stream_adapter import (
    AgenticEventStreamAdapter,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)

# CI runs ``pytest -m unit``: an unmarked module is deselected there and only
# fails on a bare local ``pytest`` run.
pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_claude_stream_uses_devnull_stdin_and_yields_output() -> None:
    adapter = AgenticEventStreamAdapter()
    adapter.set_provider(MagicMock())
    handle = IsolationHandle(
        isolation_id="container-abc123",
        isolation_type="docker",
    )
    process = MagicMock(spec=asyncio.subprocess.Process)
    process.stdout = MagicMock()
    process.stdout.readline = AsyncMock(side_effect=[b'{"type":"result"}\n', b""])
    # A real Process.wait() returns the int status. With only ``spec=`` the
    # mock's wait() resolves to another mock, which the signal-death check
    # (#1295) cannot compare to an int.
    process.wait = AsyncMock(return_value=0)
    process.returncode = 0

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as create_process:
        lines = [
            line
            async for line in adapter.stream(
                handle,
                ["claude", "-p", "hello"],
            )
        ]

    assert lines == ['{"type":"result"}']
    assert create_process.await_args.kwargs["stdin"] is asyncio.subprocess.DEVNULL
    assert adapter.last_exit_code == 0
    assert adapter.last_signal_death is None
