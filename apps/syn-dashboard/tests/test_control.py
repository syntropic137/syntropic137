"""Integration tests for control plane endpoints.

These tests mock syn_api.v1.executions to validate the dashboard's
thin-wrapper control endpoints without needing real adapters.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from syn_api.types import ControlResult, Err, ExecutionError, Ok
from syn_dashboard.main import app

API_MODULE = "syn_api.v1.executions"


def _ok_control(execution_id: str, state: str, message: str) -> Ok[ControlResult]:
    return Ok(
        ControlResult(
            success=True,
            execution_id=execution_id,
            new_state=state,
            message=message,
        )
    )


def _err_control(message: str) -> Err[ExecutionError]:
    return Err(ExecutionError.INVALID_STATE, message=message)


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.mark.unit
class TestControlHTTPEndpoints:
    """Tests for HTTP control endpoints."""

    @pytest.mark.asyncio
    async def test_get_state_unknown_execution(self, client: TestClient) -> None:
        """Test getting state for unknown execution returns 'unknown'."""
        with patch(f"{API_MODULE}.get_state", new_callable=AsyncMock) as mock:
            mock.return_value = Ok({"state": "unknown"})
            response = client.get("/executions/unknown-exec/state")
            assert response.status_code == 200
            data = response.json()
            assert data["execution_id"] == "unknown-exec"
            assert data["state"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_state_running_execution(self, client: TestClient) -> None:
        """Test getting state for running execution."""
        with patch(f"{API_MODULE}.get_state", new_callable=AsyncMock) as mock:
            mock.return_value = Ok({"state": "running"})
            response = client.get("/executions/test-exec-running/state")
            assert response.status_code == 200
            data = response.json()
            assert data["execution_id"] == "test-exec-running"
            assert data["state"] == "running"

    @pytest.mark.asyncio
    async def test_pause_running_execution(self, client: TestClient) -> None:
        """Test pausing a running execution."""
        with patch(f"{API_MODULE}.pause", new_callable=AsyncMock) as mock:
            mock.return_value = _ok_control("test-exec", "paused", "Pause signal queued")
            response = client.post(
                "/executions/test-exec/pause",
                json={"reason": "Test pause"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Pause signal queued"

    @pytest.mark.asyncio
    async def test_pause_paused_execution_fails(self, client: TestClient) -> None:
        """Test pausing an already paused execution fails."""
        with patch(f"{API_MODULE}.pause", new_callable=AsyncMock) as mock:
            mock.return_value = _err_control("Cannot pause: execution is paused")
            response = client.post("/executions/test-exec-paused/pause")
            assert response.status_code == 400
            assert "Cannot pause" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_resume_paused_execution(self, client: TestClient) -> None:
        """Test resuming a paused execution."""
        with patch(f"{API_MODULE}.resume", new_callable=AsyncMock) as mock:
            mock.return_value = _ok_control("test-exec", "running", "Resume signal queued")
            response = client.post("/executions/test-exec/resume")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Resume signal queued"

    @pytest.mark.asyncio
    async def test_resume_running_execution_fails(self, client: TestClient) -> None:
        """Test resuming a running execution fails."""
        with patch(f"{API_MODULE}.resume", new_callable=AsyncMock) as mock:
            mock.return_value = _err_control("Cannot resume: execution is running")
            response = client.post("/executions/test-exec-running/resume")
            assert response.status_code == 400
            assert "Cannot resume" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_cancel_running_execution(self, client: TestClient) -> None:
        """Test cancelling a running execution."""
        with patch(f"{API_MODULE}.cancel", new_callable=AsyncMock) as mock:
            mock.return_value = _ok_control("test-exec", "cancelled", "Cancel signal queued")
            response = client.post(
                "/executions/test-exec/cancel",
                json={"reason": "User cancelled"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Cancel signal queued"

    @pytest.mark.asyncio
    async def test_cancel_paused_execution(self, client: TestClient) -> None:
        """Test cancelling a paused execution."""
        with patch(f"{API_MODULE}.cancel", new_callable=AsyncMock) as mock:
            mock.return_value = _ok_control("test-exec", "cancelled", "Cancel signal queued")
            response = client.post("/executions/test-exec/cancel")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    @pytest.mark.asyncio
    async def test_inject_context_running_execution(self, client: TestClient) -> None:
        """Test injecting context into a running execution."""
        with patch(f"{API_MODULE}.inject", new_callable=AsyncMock) as mock:
            mock.return_value = _ok_control("test-exec", "running", "Context injection queued")
            response = client.post(
                "/executions/test-exec/inject",
                json={"message": "Additional context", "role": "user"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Context injection queued"


class TestControlWebSocket:
    """Tests for WebSocket control endpoint."""

    def test_websocket_connection(self, client: TestClient) -> None:
        """Test WebSocket connection and initial state message."""
        with patch(f"{API_MODULE}.get_state", new_callable=AsyncMock) as mock:
            mock.return_value = Ok({"state": "unknown"})
            with client.websocket_connect("/ws/control/test-exec") as websocket:
                data = websocket.receive_json()
                assert data["type"] == "state"
                assert data["execution_id"] == "test-exec"
                assert "state" in data

    @pytest.mark.asyncio
    async def test_websocket_pause_command(self, client: TestClient) -> None:
        """Test sending pause command via WebSocket."""
        with (
            patch(f"{API_MODULE}.get_state", new_callable=AsyncMock) as mock_state,
            patch(f"{API_MODULE}.pause", new_callable=AsyncMock) as mock_pause,
        ):
            mock_state.return_value = Ok({"state": "running"})
            mock_pause.return_value = _ok_control("test-exec", "paused", "Pause signal queued")
            with client.websocket_connect("/ws/control/test-exec") as websocket:
                websocket.receive_json()  # initial state
                websocket.send_json({"command": "pause", "reason": "Test"})
                data = websocket.receive_json()
                assert data["type"] == "result"
                assert data["success"] is True

    def test_websocket_unknown_command(self, client: TestClient) -> None:
        """Test sending unknown command via WebSocket."""
        with patch(f"{API_MODULE}.get_state", new_callable=AsyncMock) as mock:
            mock.return_value = Ok({"state": "unknown"})
            with client.websocket_connect("/ws/control/test-exec") as websocket:
                websocket.receive_json()  # initial state
                websocket.send_json({"command": "unknown"})
                data = websocket.receive_json()
                assert data["type"] == "error"
                assert "Unknown command" in data["error"]
