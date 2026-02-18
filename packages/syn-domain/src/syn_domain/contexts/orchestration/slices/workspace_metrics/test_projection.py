"""Tests for WorkspaceMetricsProjection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from syn_domain.contexts.orchestration.slices.workspace_metrics.projection import (
    WorkspaceMetricsProjection,
)


class MockProjectionStore:
    """In-memory store for testing projections."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def save(self, collection: str, key: str, data: dict) -> None:
        if collection not in self._data:
            self._data[collection] = {}
        self._data[collection][key] = data

    async def get(self, collection: str, key: str) -> dict | None:
        return self._data.get(collection, {}).get(key)

    async def get_all(self, collection: str) -> list[dict]:
        return list(self._data.get(collection, {}).values())

    async def query(
        self,
        collection: str,
        filters: dict | None = None,
        order_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        data = list(self._data.get(collection, {}).values())
        if filters:
            for key, value in filters.items():
                data = [d for d in data if d.get(key) == value]
        return data[offset : offset + limit]

    async def delete_all(self, collection: str) -> None:
        self._data[collection] = {}


@pytest.mark.integration
class TestWorkspaceMetricsProjection:
    """Tests for workspace metrics projection."""

    @pytest.fixture
    def store(self) -> MockProjectionStore:
        return MockProjectionStore()

    @pytest.fixture
    def projection(self, store: MockProjectionStore) -> WorkspaceMetricsProjection:
        return WorkspaceMetricsProjection(store)

    @pytest.mark.asyncio
    async def test_on_workspace_creating(
        self, projection: WorkspaceMetricsProjection, store: MockProjectionStore
    ) -> None:
        """Test WorkspaceCreating event creates initial record."""
        event_data = {
            "workspace_id": "ws-123",
            "session_id": "session-456",
            "workflow_id": "workflow-789",
            "isolation_backend": "docker_hardened",
            "started_at": datetime.now(UTC).isoformat(),
        }

        await projection.on_workspace_creating(event_data)

        # Verify record created
        record = await store.get("workspace_metrics", "ws-123")
        assert record is not None
        assert record["workspace_id"] == "ws-123"
        assert record["session_id"] == "session-456"
        assert record["workflow_id"] == "workflow-789"
        assert record["isolation_backend"] == "docker_hardened"
        assert record["status"] == "creating"

    @pytest.mark.asyncio
    async def test_on_workspace_created(
        self, projection: WorkspaceMetricsProjection, store: MockProjectionStore
    ) -> None:
        """Test WorkspaceCreated event updates status and timing."""
        # First create the workspace
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-123",
                "session_id": "session-456",
                "isolation_backend": "docker_hardened",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )

        # Then mark as created
        await projection.on_workspace_created(
            {
                "workspace_id": "ws-123",
                "session_id": "session-456",
                "create_duration_ms": 150.5,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        record = await store.get("workspace_metrics", "ws-123")
        assert record["status"] == "ready"
        assert record["create_duration_ms"] == 150.5

    @pytest.mark.asyncio
    async def test_on_command_executed(
        self, projection: WorkspaceMetricsProjection, store: MockProjectionStore
    ) -> None:
        """Test command execution updates counters."""
        # Setup workspace
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-123",
                "session_id": "session-456",
                "isolation_backend": "docker_hardened",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )

        # Execute successful command
        await projection.on_command_executed(
            {
                "workspace_id": "ws-123",
                "command": ["echo", "hello"],
                "exit_code": 0,
                "success": True,
                "duration_ms": 50.0,
            }
        )

        record = await store.get("workspace_metrics", "ws-123")
        assert record["status"] == "running"
        assert record["commands_executed"] == 1
        assert record["commands_succeeded"] == 1
        assert record["commands_failed"] == 0

        # Execute failed command
        await projection.on_command_executed(
            {
                "workspace_id": "ws-123",
                "command": ["false"],
                "exit_code": 1,
                "success": False,
                "duration_ms": 10.0,
            }
        )

        record = await store.get("workspace_metrics", "ws-123")
        assert record["commands_executed"] == 2
        assert record["commands_succeeded"] == 1
        assert record["commands_failed"] == 1

    @pytest.mark.asyncio
    async def test_on_workspace_destroyed(
        self, projection: WorkspaceMetricsProjection, store: MockProjectionStore
    ) -> None:
        """Test destruction updates final metrics."""
        # Setup workspace
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-123",
                "session_id": "session-456",
                "isolation_backend": "docker_hardened",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
        await projection.on_workspace_created(
            {
                "workspace_id": "ws-123",
                "session_id": "session-456",
                "create_duration_ms": 150.0,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        # Destroy workspace
        await projection.on_workspace_destroyed(
            {
                "workspace_id": "ws-123",
                "destroy_duration_ms": 5000.0,
                "total_lifetime_ms": 10000.0,
                "destroyed_at": datetime.now(UTC).isoformat(),
                "artifacts_collected": 3,
            }
        )

        record = await store.get("workspace_metrics", "ws-123")
        assert record["status"] == "destroyed"
        assert record["destroy_duration_ms"] == 5000.0
        assert record["total_lifetime_ms"] == 10000.0
        assert record["artifacts_collected"] == 3

    @pytest.mark.asyncio
    async def test_on_workspace_error(
        self, projection: WorkspaceMetricsProjection, store: MockProjectionStore
    ) -> None:
        """Test error event updates status."""
        # Setup workspace
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-123",
                "session_id": "session-456",
                "isolation_backend": "docker_hardened",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )

        # Error occurs
        await projection.on_workspace_error(
            {
                "workspace_id": "ws-123",
                "error_type": "RuntimeError",
                "error_message": "Container failed to start",
            }
        )

        record = await store.get("workspace_metrics", "ws-123")
        assert record["status"] == "error"
        assert record["error_type"] == "RuntimeError"
        assert record["error_message"] == "Container failed to start"

    @pytest.mark.asyncio
    async def test_get_summary(
        self,
        projection: WorkspaceMetricsProjection,
        store: MockProjectionStore,
    ) -> None:
        """Test aggregated summary calculation."""
        # Create multiple workspaces with different backends
        for i, backend in enumerate(["docker_hardened", "docker_hardened", "gvisor"]):
            ws_id = f"ws-{i}"
            await projection.on_workspace_creating(
                {
                    "workspace_id": ws_id,
                    "session_id": f"session-{i}",
                    "isolation_backend": backend,
                    "started_at": datetime.now(UTC).isoformat(),
                }
            )
            await projection.on_workspace_created(
                {
                    "workspace_id": ws_id,
                    "session_id": f"session-{i}",
                    "create_duration_ms": 100.0 + (i * 50),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            # Execute some commands
            await projection.on_command_executed(
                {
                    "workspace_id": ws_id,
                    "command": ["echo", "test"],
                    "exit_code": 0,
                    "success": True,
                    "duration_ms": 50.0,
                }
            )
            await projection.on_workspace_destroyed(
                {
                    "workspace_id": ws_id,
                    "destroy_duration_ms": 5000.0,
                    "total_lifetime_ms": 10000.0 + (i * 1000),
                    "destroyed_at": datetime.now(UTC).isoformat(),
                }
            )

        summary = await projection.get_summary()

        assert summary.total_workspaces == 3
        assert summary.workspaces_by_backend == {"docker_hardened": 2, "gvisor": 1}
        assert summary.workspaces_by_status == {"destroyed": 3}
        assert summary.avg_create_duration_ms == 150.0  # (100 + 150 + 200) / 3
        assert summary.total_commands_executed == 3
        assert summary.command_success_rate == 1.0
        assert summary.error_count == 0

    @pytest.mark.asyncio
    async def test_get_by_session(
        self,
        projection: WorkspaceMetricsProjection,
        store: MockProjectionStore,
    ) -> None:
        """Test querying by session ID."""
        # Create workspaces for different sessions
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-1",
                "session_id": "session-A",
                "isolation_backend": "docker_hardened",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-2",
                "session_id": "session-B",
                "isolation_backend": "docker_hardened",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
        await projection.on_workspace_creating(
            {
                "workspace_id": "ws-3",
                "session_id": "session-A",
                "isolation_backend": "gvisor",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )

        # Query for session A
        session_a_metrics = await projection.get_by_session("session-A")
        assert len(session_a_metrics) == 2
        assert all(m.session_id == "session-A" for m in session_a_metrics)

        # Query for session B
        session_b_metrics = await projection.get_by_session("session-B")
        assert len(session_b_metrics) == 1
        assert session_b_metrics[0].session_id == "session-B"
