"""Projection for session list view.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary,
)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "SessionStarted",
    "OperationRecorded",
    "SessionCompleted",
    "SubagentStarted",
    "SubagentStopped",
}


def _calculate_duration(
    started_at: str | datetime | None, completed_at: str | datetime | None
) -> float | None:
    """Calculate duration in seconds between two timestamps.

    Handles both datetime objects and ISO strings.
    """
    if not started_at or not completed_at:
        return None

    try:
        # Parse if string
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))

        return (completed_at - started_at).total_seconds()
    except (ValueError, TypeError):
        return None


class SessionListProjection(CheckpointedProjection):
    """Builds session list read model from events.

    This projection maintains a summary view of all sessions for
    efficient listing and filtering.

    Implements CheckpointedProjection for per-projection position tracking.
    """

    PROJECTION_NAME = "session_summaries"
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
            if event_type == "SessionStarted":
                await self.on_session_started(event_data)
            elif event_type == "OperationRecorded":
                await self.on_operation_recorded(event_data)
            elif event_type == "SessionCompleted":
                await self.on_session_completed(event_data)
            elif event_type == "SubagentStarted":
                await self.on_subagent_started(event_data)
            elif event_type == "SubagentStopped":
                await self.on_subagent_stopped(event_data)

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

    async def on_session_started(self, event_data: dict) -> None:
        """Handle SessionStarted event."""
        session_id = event_data.get("session_id", "")
        summary = SessionSummary(
            id=session_id,
            workflow_id=event_data.get("workflow_id", ""),
            agent_type=event_data.get("agent_provider", "unknown"),
            status="running",
            total_tokens=0,
            total_cost_usd=Decimal("0"),
            started_at=event_data.get("started_at"),
            completed_at=None,
            input_tokens=0,
            output_tokens=0,
            duration_seconds=None,
            phase_id=event_data.get("phase_id"),
            execution_id=event_data.get("execution_id"),  # Link to workflow execution
        )
        await self._store.save(self.PROJECTION_NAME, session_id, summary.to_dict())

    async def on_operation_recorded(self, event_data: dict) -> None:
        """Handle OperationRecorded - update token counts and store operation.

        Handles both v1 and v2 event formats for backward compatibility.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            # Accumulate tokens from operation (for MESSAGE_RESPONSE operations)
            op_tokens = event_data.get("total_tokens", 0) or event_data.get("tokens_used", 0)
            if op_tokens:
                existing["total_tokens"] = existing.get("total_tokens", 0) + op_tokens
                # Also accumulate input/output tokens
                input_toks = event_data.get("input_tokens", 0) or 0
                output_toks = event_data.get("output_tokens", 0) or 0
                existing["input_tokens"] = existing.get("input_tokens", 0) + input_toks
                existing["output_tokens"] = existing.get("output_tokens", 0) + output_toks

            existing["total_cost_usd"] = float(
                Decimal(str(existing.get("total_cost_usd", 0)))
                + Decimal(str(event_data.get("cost_usd", 0)))
            )

            # Store the operation with all fields (v2 event format)
            operations = existing.get("operations", [])
            operations.append(
                {
                    "operation_id": event_data.get("operation_id", ""),
                    "operation_type": event_data.get("operation_type", ""),
                    "timestamp": event_data.get("timestamp"),
                    "duration_seconds": event_data.get("duration_seconds"),
                    "success": event_data.get("success", True),
                    # Token metrics
                    "input_tokens": event_data.get("input_tokens"),
                    "output_tokens": event_data.get("output_tokens"),
                    "total_tokens": event_data.get("total_tokens"),
                    # Tool details
                    "tool_name": event_data.get("tool_name"),
                    "tool_use_id": event_data.get("tool_use_id"),
                    "tool_input": event_data.get("tool_input"),
                    "tool_output": event_data.get("tool_output"),
                    # Message details
                    "message_role": event_data.get("message_role"),
                    "message_content": event_data.get("message_content"),
                    # Thinking details
                    "thinking_content": event_data.get("thinking_content"),
                }
            )
            existing["operations"] = operations

            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def on_session_completed(self, event_data: dict) -> None:
        """Handle SessionCompleted event."""
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            existing["status"] = event_data.get("status", "completed")
            existing["completed_at"] = event_data.get("completed_at")

            # Token breakdown - extract input/output separately
            existing["input_tokens"] = event_data.get("total_input_tokens", 0)
            existing["output_tokens"] = event_data.get("total_output_tokens", 0)
            existing["total_tokens"] = event_data.get(
                "total_tokens", existing.get("total_tokens", 0)
            )
            existing["total_cost_usd"] = float(
                Decimal(str(event_data.get("total_cost_usd", existing.get("total_cost_usd", 0))))
            )

            # Duration calculation
            started_at = existing.get("started_at")
            completed_at = event_data.get("completed_at")
            if started_at and completed_at:
                existing["duration_seconds"] = _calculate_duration(started_at, completed_at)

            # Enhanced metrics from result event (agentic_isolation v0.3.0)
            if "num_turns" in event_data:
                existing["num_turns"] = event_data["num_turns"]
            if "duration_api_ms" in event_data:
                existing["duration_api_ms"] = event_data["duration_api_ms"]

            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def on_subagent_started(self, event_data: dict) -> None:
        """Handle SubagentStarted event - track subagent spawn.

        Creates a new subagent record and increments subagent_count.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            # Initialize subagent tracking if needed
            subagents = existing.get("subagents", [])
            subagent_count = existing.get("subagent_count", 0)

            # Create new subagent record
            subagent_record = {
                "subagent_tool_use_id": event_data.get("subagent_tool_use_id", ""),
                "agent_name": event_data.get("agent_name", ""),
                "started_at": event_data.get("timestamp"),
                "stopped_at": None,
                "duration_ms": None,
                "tools_used": {},
                "success": True,
            }

            subagents.append(subagent_record)
            existing["subagents"] = subagents
            existing["subagent_count"] = subagent_count + 1

            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def on_subagent_stopped(self, event_data: dict) -> None:
        """Handle SubagentStopped event - update subagent record with completion data.

        Updates the matching subagent record with duration and tools used.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            subagents = existing.get("subagents", [])
            subagent_tool_use_id = event_data.get("subagent_tool_use_id", "")

            # Find and update the matching subagent record
            for subagent in subagents:
                if subagent.get("subagent_tool_use_id") == subagent_tool_use_id:
                    subagent["stopped_at"] = event_data.get("timestamp")
                    subagent["duration_ms"] = event_data.get("duration_ms")
                    subagent["tools_used"] = event_data.get("tools_used", {})
                    subagent["success"] = event_data.get("success", True)
                    break

            existing["subagents"] = subagents

            # Aggregate tools_by_subagent
            tools_by_subagent = existing.get("tools_by_subagent", {})
            agent_name = event_data.get("agent_name", "unknown")
            tools_used = event_data.get("tools_used", {})
            if tools_used:
                tools_by_subagent[agent_name] = tools_used
            existing["tools_by_subagent"] = tools_by_subagent

            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def get_all(self) -> list[SessionSummary]:
        """Get all sessions."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [SessionSummary.from_dict(d) for d in data]

    async def get_by_workflow(self, workflow_id: str) -> list[SessionSummary]:
        """Get sessions for a specific workflow."""
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"workflow_id": workflow_id},
        )
        return [SessionSummary.from_dict(d) for d in data]

    async def query(
        self,
        workflow_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-started_at",
    ) -> list[SessionSummary]:
        """Query sessions with optional filtering."""
        filters = {}
        if workflow_id:
            filters["workflow_id"] = workflow_id
        if status_filter:
            filters["status"] = status_filter

        data = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters if filters else None,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [SessionSummary.from_dict(d) for d in data]

    async def reconcile_orphaned(
        self,
        error_message: str = "Orphaned: framework restarted while agent was active",
    ) -> int:
        """Mark all running sessions as failed.

        Call this during startup to clean up sessions that were active when
        the framework was previously stopped (container crash, kill, restart).
        Returns the count of sessions reconciled.
        """
        running = await self.query(status_filter="running", limit=1000)
        if not running:
            return 0

        now_iso = datetime.now(UTC).isoformat()
        count = 0
        for session in running:
            try:
                data = await self._store.get(self.PROJECTION_NAME, session.id)
                if data and data.get("status") == "running":
                    data["status"] = "failed"
                    data["completed_at"] = now_iso
                    data["error_message"] = error_message
                    await self._store.save(self.PROJECTION_NAME, session.id, data)
                    count += 1
            except Exception:
                pass
        return count
