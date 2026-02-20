"""Unit tests for ManagedWorkspace.interrupt() method.

T-4: Verifies SIGINT delivery via docker exec with mocked subprocess.
All tests are unit tests with no Docker dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class _MockIsolationHandle:
    """Minimal mock for IsolationHandle with container_id."""

    container_id: str = "agentic-ws-abc123"
    workspace_path: str = "/workspace"
    host_workspace_path: str | None = None


def _make_managed_workspace(container_id: str = "agentic-ws-abc123"):
    """Create a ManagedWorkspace with mocked internals."""
    from syn_adapters.workspace_backends.service.workspace_service import ManagedWorkspace

    mock_service = MagicMock()
    mock_aggregate = MagicMock()

    return ManagedWorkspace(
        workspace_id="ws-1",
        execution_id="exec-1",
        aggregate=mock_aggregate,
        isolation_handle=_MockIsolationHandle(container_id=container_id),
        sidecar_handle=None,
        _service=mock_service,
    )


@pytest.mark.unit
class TestManagedWorkspaceInterrupt:
    """T-4: Tests for ManagedWorkspace.interrupt()."""

    @pytest.mark.asyncio
    async def test_sends_sigint_to_claude_process(self) -> None:
        """interrupt() calls docker exec with kill -INT and returns True on success."""
        workspace = _make_managed_workspace("my-container-id")

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await workspace.interrupt()

        assert result is True
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        # docker exec <container_id> sh -c "kill -INT ..."
        assert "docker" in call_args
        assert "exec" in call_args
        assert "my-container-id" in call_args
        assert "sh" in call_args

    @pytest.mark.asyncio
    async def test_returns_false_on_subprocess_failure(self) -> None:
        """interrupt() returns False when docker exec exits non-zero (non-fatal)."""
        workspace = _make_managed_workspace()

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await workspace.interrupt()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_container_id(self) -> None:
        """interrupt() returns False gracefully when container_id is missing."""
        workspace = _make_managed_workspace()
        workspace.isolation_handle = _MockIsolationHandle(container_id="")

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await workspace.interrupt()

        assert result is False
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self) -> None:
        """interrupt() returns False (non-fatal) when subprocess raises."""
        workspace = _make_managed_workspace()

        with patch("asyncio.create_subprocess_exec", side_effect=OSError("docker not found")):
            result = await workspace.interrupt()

        assert result is False
