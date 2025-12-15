"""Tests for streaming execution protocol."""

from __future__ import annotations

from unittest import mock

import pytest

from aef_adapters.workspaces.base import BaseIsolatedWorkspace


class TestExecuteStreaming:
    """Tests for execute_streaming method."""

    @pytest.mark.asyncio
    async def test_requires_container_id(self) -> None:
        """Should raise if no container ID available."""
        # Create mock workspace with no container ID
        workspace = mock.MagicMock()
        workspace.container_id = None
        workspace.vm_id = None
        workspace.sandbox_id = None

        with pytest.raises(RuntimeError, match="No container ID"):
            async for _ in BaseIsolatedWorkspace.execute_streaming(
                workspace,
                ["python", "-m", "aef_agent_runner"],
            ):
                pass

    @pytest.mark.asyncio
    async def test_streams_stdout_lines(self) -> None:
        """Should yield lines from stdout."""
        workspace = mock.MagicMock()
        workspace.container_id = "test-container-123"
        workspace.vm_id = None
        workspace.sandbox_id = None

        # Mock the subprocess
        mock_process = mock.AsyncMock()
        mock_process.returncode = 0

        # Create async iterator for stdout
        async def mock_stdout_iter():
            yield b'{"type": "started"}\n'
            yield b'{"type": "progress", "turn": 1}\n'
            yield b'{"type": "completed"}\n'

        mock_process.stdout = mock_stdout_iter()
        mock_process.stderr = mock.AsyncMock()
        mock_process.wait = mock.AsyncMock()

        with mock.patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            lines = []
            async for line in BaseIsolatedWorkspace.execute_streaming(
                workspace,
                ["python", "-m", "aef_agent_runner"],
            ):
                lines.append(line)

            assert len(lines) == 3
            assert '{"type": "started"}' in lines[0]
            assert '{"type": "completed"}' in lines[2]

    @pytest.mark.asyncio
    async def test_raises_on_failure(self) -> None:
        """Should raise RuntimeError on non-zero exit."""
        workspace = mock.MagicMock()
        workspace.container_id = "test-container-123"
        workspace.vm_id = None
        workspace.sandbox_id = None

        mock_process = mock.AsyncMock()
        mock_process.returncode = 1

        async def empty_iter():
            return
            yield  # Make it an async generator

        mock_process.stdout = empty_iter()
        mock_process.stderr = mock.AsyncMock()
        mock_process.stderr.read = mock.AsyncMock(return_value=b"Error: something failed")
        mock_process.wait = mock.AsyncMock()

        with (
            mock.patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ),
            pytest.raises(RuntimeError, match="exit code 1"),
        ):
            async for _ in BaseIsolatedWorkspace.execute_streaming(
                workspace,
                ["python", "-m", "aef_agent_runner"],
            ):
                pass


class TestRequestCancellation:
    """Tests for request_cancellation method."""

    @pytest.mark.asyncio
    async def test_creates_cancel_file(self) -> None:
        """Should create .cancel file in workspace."""
        workspace = mock.MagicMock()
        workspace.container_id = "test-container-123"
        workspace.vm_id = None
        workspace.sandbox_id = None

        mock_process = mock.AsyncMock()
        mock_process.returncode = 0
        mock_process.wait = mock.AsyncMock()

        with mock.patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ) as mock_exec:
            await BaseIsolatedWorkspace.request_cancellation(workspace)

            # Verify docker exec touch was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert "docker" in call_args
            assert "exec" in call_args
            assert "touch" in call_args
            assert "/workspace/.cancel" in call_args

    @pytest.mark.asyncio
    async def test_handles_no_container(self) -> None:
        """Should not fail if no container ID."""
        workspace = mock.MagicMock()
        workspace.container_id = None
        workspace.vm_id = None
        workspace.sandbox_id = None

        # Should not raise
        await BaseIsolatedWorkspace.request_cancellation(workspace)
