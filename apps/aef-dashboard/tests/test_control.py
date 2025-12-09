"""Integration tests for control plane endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aef_adapters.control import ExecutionState
from aef_dashboard.main import app
from aef_dashboard.services.control import get_state_adapter


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
async def running_execution() -> str:
    """Create an execution in running state."""
    execution_id = "test-exec-running"
    state_adapter = get_state_adapter()
    await state_adapter.save_state(execution_id, ExecutionState.RUNNING)
    return execution_id


@pytest.fixture
async def paused_execution() -> str:
    """Create an execution in paused state."""
    execution_id = "test-exec-paused"
    state_adapter = get_state_adapter()
    await state_adapter.save_state(execution_id, ExecutionState.PAUSED)
    return execution_id


class TestControlHTTPEndpoints:
    """Tests for HTTP control endpoints."""

    @pytest.mark.asyncio
    async def test_get_state_unknown_execution(self, client: TestClient) -> None:
        """Test getting state for unknown execution returns 'unknown'."""
        response = client.get("/api/executions/unknown-exec/state")
        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == "unknown-exec"
        assert data["state"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_state_running_execution(
        self, client: TestClient, running_execution: str
    ) -> None:
        """Test getting state for running execution."""
        response = client.get(f"/api/executions/{running_execution}/state")
        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == running_execution
        assert data["state"] == "running"

    @pytest.mark.asyncio
    async def test_pause_running_execution(
        self, client: TestClient, running_execution: str
    ) -> None:
        """Test pausing a running execution."""
        response = client.post(
            f"/api/executions/{running_execution}/pause",
            json={"reason": "Test pause"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Pause signal queued"

    @pytest.mark.asyncio
    async def test_pause_paused_execution_fails(
        self, client: TestClient, paused_execution: str
    ) -> None:
        """Test pausing an already paused execution fails."""
        response = client.post(f"/api/executions/{paused_execution}/pause")
        assert response.status_code == 400
        assert "Cannot pause" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_resume_paused_execution(
        self, client: TestClient, paused_execution: str
    ) -> None:
        """Test resuming a paused execution."""
        response = client.post(f"/api/executions/{paused_execution}/resume")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Resume signal queued"

    @pytest.mark.asyncio
    async def test_resume_running_execution_fails(
        self, client: TestClient, running_execution: str
    ) -> None:
        """Test resuming a running execution fails."""
        response = client.post(f"/api/executions/{running_execution}/resume")
        assert response.status_code == 400
        assert "Cannot resume" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_cancel_running_execution(
        self, client: TestClient, running_execution: str
    ) -> None:
        """Test cancelling a running execution."""
        response = client.post(
            f"/api/executions/{running_execution}/cancel",
            json={"reason": "User cancelled"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Cancel signal queued"

    @pytest.mark.asyncio
    async def test_cancel_paused_execution(
        self, client: TestClient, paused_execution: str
    ) -> None:
        """Test cancelling a paused execution."""
        response = client.post(f"/api/executions/{paused_execution}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_inject_context_running_execution(
        self, client: TestClient, running_execution: str
    ) -> None:
        """Test injecting context into a running execution."""
        response = client.post(
            f"/api/executions/{running_execution}/inject",
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
        with client.websocket_connect("/api/ws/control/test-exec") as websocket:
            # Should receive initial state message
            data = websocket.receive_json()
            assert data["type"] == "state"
            assert data["execution_id"] == "test-exec"
            assert "state" in data

    @pytest.mark.asyncio
    async def test_websocket_pause_command(
        self, client: TestClient, running_execution: str
    ) -> None:
        """Test sending pause command via WebSocket."""
        with client.websocket_connect(
            f"/api/ws/control/{running_execution}"
        ) as websocket:
            # Receive initial state
            websocket.receive_json()

            # Send pause command
            websocket.send_json({"command": "pause", "reason": "Test"})

            # Receive result
            data = websocket.receive_json()
            assert data["type"] == "result"
            assert data["success"] is True

    def test_websocket_unknown_command(self, client: TestClient) -> None:
        """Test sending unknown command via WebSocket."""
        with client.websocket_connect("/api/ws/control/test-exec") as websocket:
            # Receive initial state
            websocket.receive_json()

            # Send unknown command
            websocket.send_json({"command": "unknown"})

            # Receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Unknown command" in data["error"]
