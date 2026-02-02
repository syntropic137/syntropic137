"""Projection for workspace metrics.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from datetime import UTC, datetime
from typing import Any

from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from aef_domain.contexts.orchestration.domain.read_models.workspace_metrics import (
    WorkspaceMetrics,
    WorkspaceMetricsSummary,
)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "WorkspaceCreating",
    "WorkspaceCreated",
    "WorkspaceCommandExecuted",
    "WorkspaceDestroying",
    "WorkspaceDestroyed",
    "WorkspaceError",
}


class WorkspaceMetricsProjection(CheckpointedProjection):
    """Builds workspace metrics read model from lifecycle events.

    Tracks:
    - Workspace creation/destruction timing
    - Command execution stats
    - Error rates by backend
    - Performance metrics for observability

    Implements CheckpointedProjection for per-projection position tracking.
    """

    PROJECTION_NAME = "workspace_metrics"
    VERSION = 1

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    # === CheckpointedProjection required methods ===

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        """Event types this projection handles."""
        return _SUBSCRIBED_EVENTS

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        """Handle an event and save checkpoint atomically."""
        event_type = envelope.event.event_type
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            if event_type == "WorkspaceCreating":
                await self.on_workspace_creating(event_data)
            elif event_type == "WorkspaceCreated":
                await self.on_workspace_created(event_data)
            elif event_type == "WorkspaceCommandExecuted":
                await self.on_command_executed(event_data)
            elif event_type == "WorkspaceDestroying":
                await self.on_workspace_destroying(event_data)
            elif event_type == "WorkspaceDestroyed":
                await self.on_workspace_destroyed(event_data)
            elif event_type == "WorkspaceError":
                await self.on_workspace_error(event_data)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception:
            return ProjectionResult.FAILURE

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    @property
    def name(self) -> str:
        """Get the projection name (deprecated, use get_name())."""
        return self.PROJECTION_NAME

    # === Event handlers ===

    async def on_workspace_creating(self, event_data: dict) -> None:
        """Handle WorkspaceCreating event."""
        workspace_id = event_data.get("workspace_id", "")
        metrics = WorkspaceMetrics(
            workspace_id=workspace_id,
            session_id=event_data.get("session_id", ""),
            workflow_id=event_data.get("workflow_id"),
            execution_id=event_data.get("execution_id"),
            isolation_backend=event_data.get("isolation_backend", "unknown"),
            status="creating",
            created_at=self._parse_datetime(event_data.get("started_at")),
        )
        await self._store.save(self.PROJECTION_NAME, workspace_id, metrics.to_dict())

    async def on_workspace_created(self, event_data: dict) -> None:
        """Handle WorkspaceCreated event."""
        workspace_id = event_data.get("workspace_id", "")

        existing = await self._store.get(self.PROJECTION_NAME, workspace_id)
        if existing:
            existing["status"] = "ready"
            existing["create_duration_ms"] = event_data.get("create_duration_ms")
            existing["created_at"] = event_data.get("created_at")
            await self._store.save(self.PROJECTION_NAME, workspace_id, existing)
        else:
            # Create new if missed WorkspaceCreating
            metrics = WorkspaceMetrics(
                workspace_id=workspace_id,
                session_id=event_data.get("session_id", ""),
                workflow_id=event_data.get("workflow_id"),
                execution_id=event_data.get("execution_id"),
                isolation_backend=event_data.get("isolation_backend", "unknown"),
                status="ready",
                create_duration_ms=event_data.get("create_duration_ms"),
                created_at=self._parse_datetime(event_data.get("created_at")),
            )
            await self._store.save(self.PROJECTION_NAME, workspace_id, metrics.to_dict())

    async def on_command_executed(self, event_data: dict) -> None:
        """Handle WorkspaceCommandExecuted event."""
        workspace_id = event_data.get("workspace_id", "")

        existing = await self._store.get(self.PROJECTION_NAME, workspace_id)
        if existing:
            existing["status"] = "running"
            existing["commands_executed"] = existing.get("commands_executed", 0) + 1
            if event_data.get("success", False):
                existing["commands_succeeded"] = existing.get("commands_succeeded", 0) + 1
            else:
                existing["commands_failed"] = existing.get("commands_failed", 0) + 1
            await self._store.save(self.PROJECTION_NAME, workspace_id, existing)

    async def on_workspace_destroying(self, event_data: dict) -> None:
        """Handle WorkspaceDestroying event."""
        workspace_id = event_data.get("workspace_id", "")

        existing = await self._store.get(self.PROJECTION_NAME, workspace_id)
        if existing:
            existing["status"] = "destroying"
            await self._store.save(self.PROJECTION_NAME, workspace_id, existing)

    async def on_workspace_destroyed(self, event_data: dict) -> None:
        """Handle WorkspaceDestroyed event."""
        workspace_id = event_data.get("workspace_id", "")

        existing = await self._store.get(self.PROJECTION_NAME, workspace_id)
        if existing:
            existing["status"] = "destroyed"
            existing["destroy_duration_ms"] = event_data.get("destroy_duration_ms")
            existing["total_lifetime_ms"] = event_data.get("total_lifetime_ms")
            existing["destroyed_at"] = event_data.get("destroyed_at")
            existing["artifacts_collected"] = event_data.get("artifacts_collected", 0)
            await self._store.save(self.PROJECTION_NAME, workspace_id, existing)

    async def on_workspace_error(self, event_data: dict) -> None:
        """Handle WorkspaceError event."""
        workspace_id = event_data.get("workspace_id", "")

        existing = await self._store.get(self.PROJECTION_NAME, workspace_id)
        if existing:
            existing["status"] = "error"
            existing["error_type"] = event_data.get("error_type")
            existing["error_message"] = event_data.get("error_message")
            await self._store.save(self.PROJECTION_NAME, workspace_id, existing)
        else:
            # Create with error state
            metrics = WorkspaceMetrics(
                workspace_id=workspace_id,
                session_id=event_data.get("session_id", ""),
                isolation_backend=event_data.get("isolation_backend", "unknown"),
                status="error",
                error_type=event_data.get("error_type"),
                error_message=event_data.get("error_message"),
            )
            await self._store.save(self.PROJECTION_NAME, workspace_id, metrics.to_dict())

    # === Query methods ===

    async def get_all(self) -> list[WorkspaceMetrics]:
        """Get all workspace metrics."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [WorkspaceMetrics.from_dict(d) for d in data]

    async def get_by_session(self, session_id: str) -> list[WorkspaceMetrics]:
        """Get metrics for a specific session."""
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"session_id": session_id},
        )
        return [WorkspaceMetrics.from_dict(d) for d in data]

    async def get_by_backend(self, isolation_backend: str) -> list[WorkspaceMetrics]:
        """Get metrics for a specific backend."""
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"isolation_backend": isolation_backend},
        )
        return [WorkspaceMetrics.from_dict(d) for d in data]

    async def get_summary(self) -> WorkspaceMetricsSummary:
        """Get aggregated metrics summary."""
        all_metrics = await self.get_all()

        if not all_metrics:
            return WorkspaceMetricsSummary()

        # Aggregate
        by_backend: dict[str, int] = {}
        by_status: dict[str, int] = {}
        create_times: list[float] = []
        destroy_times: list[float] = []
        lifetime_times: list[float] = []
        error_count = 0
        total_commands = 0
        successful_commands = 0

        for m in all_metrics:
            by_backend[m.isolation_backend] = by_backend.get(m.isolation_backend, 0) + 1
            by_status[m.status] = by_status.get(m.status, 0) + 1

            if m.create_duration_ms is not None:
                create_times.append(m.create_duration_ms)
            if m.destroy_duration_ms is not None:
                destroy_times.append(m.destroy_duration_ms)
            if m.total_lifetime_ms is not None:
                lifetime_times.append(m.total_lifetime_ms)

            if m.status == "error":
                error_count += 1

            total_commands += m.commands_executed
            successful_commands += m.commands_succeeded

        def avg(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        def p95(values: list[float]) -> float:
            if not values:
                return 0.0
            sorted_values = sorted(values)
            idx = int(len(sorted_values) * 0.95)
            return sorted_values[min(idx, len(sorted_values) - 1)]

        return WorkspaceMetricsSummary(
            total_workspaces=len(all_metrics),
            workspaces_by_backend=by_backend,
            workspaces_by_status=by_status,
            avg_create_duration_ms=avg(create_times),
            avg_destroy_duration_ms=avg(destroy_times),
            avg_total_lifetime_ms=avg(lifetime_times),
            p95_create_duration_ms=p95(create_times),
            p95_destroy_duration_ms=p95(destroy_times),
            error_count=error_count,
            error_rate=error_count / len(all_metrics) if all_metrics else 0.0,
            total_commands_executed=total_commands,
            command_success_rate=(
                successful_commands / total_commands if total_commands > 0 else 1.0
            ),
        )

    # === Helpers ===

    def _parse_datetime(self, value: str | datetime | None) -> datetime | None:
        """Parse datetime from string or return as-is."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
