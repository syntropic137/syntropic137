"""Projection for session list view.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary,
)

logger = logging.getLogger(__name__)


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


def _coerce_iso_datetime(value: object) -> datetime | None:
    """Parse an ISO 8601 string or accept an existing datetime; return None on failure.

    Handles the trailing ``Z`` suffix (RFC 3339) which ``fromisoformat`` rejects
    on Python <3.11.
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _within_window(
    record: Any,
    after: datetime | None,
    before: datetime | None,
) -> bool:
    """True if ``record['started_at']`` is within [after, before]."""
    started = _coerce_iso_datetime(record.get("started_at"))
    if started is None:
        return False
    if after is not None and started < after:
        return False
    return not (before is not None and started > before)


def _build_query_filters(
    workflow_id: str | None,
    status_filter: str | None,
    statuses: list[str] | None,
) -> dict[str, str]:
    """Build the equality filter map for store.query()."""
    filters: dict[str, str] = {}
    if workflow_id:
        filters["workflow_id"] = workflow_id
    if status_filter and not statuses:
        filters["status"] = status_filter
    return filters


def _apply_post_filters(
    data: list[Any],
    statuses: list[str] | None,
    started_after: datetime | None,
    started_before: datetime | None,
    offset: int,
    limit: int,
) -> list[Any]:
    """Apply the in-memory filters that the store cannot express, then paginate."""
    if statuses:
        allowed = set(statuses)
        data = [d for d in data if d.get("status") in allowed]
    if started_after is not None or started_before is not None:
        data = [d for d in data if _within_window(d, started_after, started_before)]
    return data[offset : offset + limit] if limit else data[offset:]


def _accumulate_tokens(existing: dict[str, Any], event_data: dict) -> None:
    """Accumulate token counts from an operation event."""
    op_tokens = event_data.get("total_tokens", 0) or event_data.get("tokens_used", 0)
    if op_tokens:
        existing["total_tokens"] = existing.get("total_tokens", 0) + op_tokens
        existing["input_tokens"] = existing.get("input_tokens", 0) + (
            event_data.get("input_tokens", 0) or 0
        )
        existing["output_tokens"] = existing.get("output_tokens", 0) + (
            event_data.get("output_tokens", 0) or 0
        )
        existing["cache_creation_tokens"] = existing.get("cache_creation_tokens", 0) + (
            event_data.get("cache_creation_tokens", 0) or 0
        )
        existing["cache_read_tokens"] = existing.get("cache_read_tokens", 0) + (
            event_data.get("cache_read_tokens", 0) or 0
        )


_OPERATION_FIELDS = [
    "operation_id",
    "operation_type",
    "timestamp",
    "duration_seconds",
    "success",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tool_name",
    "tool_use_id",
    "tool_input",
    "tool_output",
    "message_role",
    "message_content",
    "thinking_content",
]

_OPERATION_DEFAULTS: dict[str, Any] = {"operation_id": "", "operation_type": "", "success": True}


def _apply_session_completed(existing: dict[str, Any], event_data: dict) -> None:
    """Apply SessionCompleted fields to an existing session record."""
    existing["status"] = event_data.get("status", "completed")
    existing["completed_at"] = event_data.get("completed_at")
    existing["input_tokens"] = event_data.get("total_input_tokens", 0)
    existing["output_tokens"] = event_data.get("total_output_tokens", 0)
    existing["cache_creation_tokens"] = event_data.get("total_cache_creation_tokens", 0)
    existing["cache_read_tokens"] = event_data.get("total_cache_read_tokens", 0)
    existing["total_tokens"] = event_data.get("total_tokens", existing.get("total_tokens", 0))
    started_at = existing.get("started_at")
    completed_at = event_data.get("completed_at")
    if started_at and completed_at:
        existing["duration_seconds"] = _calculate_duration(started_at, completed_at)
    if event_data.get("error_message"):
        existing["error_message"] = event_data["error_message"]
    if "num_turns" in event_data:
        existing["num_turns"] = event_data["num_turns"]
    if "duration_api_ms" in event_data:
        existing["duration_api_ms"] = event_data["duration_api_ms"]


def _append_operation(existing: dict[str, Any], event_data: dict) -> None:
    """Append an operation record to the session's operations list."""
    operation = {
        field: event_data.get(field, _OPERATION_DEFAULTS.get(field)) for field in _OPERATION_FIELDS
    }
    operations = existing.get("operations", [])
    operations.append(operation)
    existing["operations"] = operations


def _update_subagent_record(
    subagents: list[dict[str, Any]],
    event_data: dict,
) -> None:
    """Find and update the matching subagent record with completion data."""
    subagent_tool_use_id = event_data.get("subagent_tool_use_id", "")
    for subagent in subagents:
        if subagent.get("subagent_tool_use_id") == subagent_tool_use_id:
            subagent["stopped_at"] = event_data.get("timestamp")
            subagent["duration_ms"] = event_data.get("duration_ms")
            subagent["tools_used"] = event_data.get("tools_used", {})
            subagent["success"] = event_data.get("success", True)
            break


class SessionListProjection(AutoDispatchProjection):
    """Builds session list read model from events.

    This projection maintains a summary view of all sessions for
    efficient listing and filtering.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "session_summaries"
    VERSION = 3  # Bumped: unified token counting - cache tokens (#695)

    def __init__(self, store: ProjectionStore):
        """Initialize with a projection store.

        Args:
            store: A ProjectionStore implementation
        """
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def on_session_started(self, event_data: dict) -> None:
        """Handle SessionStarted event."""
        session_id = event_data.get("session_id", "")
        summary = SessionSummary(
            id=session_id,
            workflow_id=event_data.get("workflow_id", ""),
            agent_type=event_data.get("agent_provider", "unknown"),
            status="running",
            total_tokens=0,
            started_at=event_data.get("started_at"),
            completed_at=None,
            input_tokens=0,
            output_tokens=0,
            duration_seconds=None,
            phase_id=event_data.get("phase_id"),
            execution_id=event_data.get("execution_id"),
        )
        await self._store.save(self.PROJECTION_NAME, session_id, summary.to_dict())

    async def on_operation_recorded(self, event_data: dict) -> None:
        """Handle OperationRecorded - update token counts and store operation."""
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            _accumulate_tokens(existing, event_data)
            _append_operation(existing, event_data)
            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def on_session_completed(self, event_data: dict) -> None:
        """Handle SessionCompleted event."""
        session_id = event_data.get("session_id")
        if not session_id:
            return
        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            _apply_session_completed(existing, event_data)
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
        """Handle SubagentStopped event - update subagent record with completion data."""
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            subagents = existing.get("subagents", [])
            _update_subagent_record(subagents, event_data)
            existing["subagents"] = subagents

            tools_used = event_data.get("tools_used", {})
            if tools_used:
                tools_by_subagent = existing.get("tools_by_subagent", {})
                tools_by_subagent[event_data.get("agent_name", "unknown")] = tools_used
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
        statuses: list[str] | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-started_at",
    ) -> list[SessionSummary]:
        """Query sessions with optional filtering.

        ``statuses`` (multi-select) takes precedence over ``status_filter``
        (single value, kept for backwards compatibility).

        Time-range filters (``started_after`` / ``started_before``) are applied
        post-fetch in Python because the underlying store filter only supports
        equality. We fetch without a row cap when bounds are present so the
        bounded slice is honoured even on installs with many sessions.
        """
        filters = _build_query_filters(workflow_id, status_filter, statuses)
        post_filtering = bool(
            statuses or started_after is not None or started_before is not None
        )
        store_limit = None if post_filtering else limit
        store_offset = 0 if post_filtering else offset

        data = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters if filters else None,
            order_by=order_by,
            limit=store_limit,
            offset=store_offset,
        )

        if post_filtering:
            data = _apply_post_filters(
                data, statuses, started_after, started_before, offset, limit
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
                logger.exception("Failed to reconcile session %s", session.id)
        return count
