"""Projection for session list view.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.agent_sessions._shared.value_objects import AgentLaunch
from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary,
)
from syn_domain.pagination import Page, matches_search, paginate, within_window

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


def _build_query_filters(
    workflow_id: str | None,
    status_filter: str | None,
    statuses: list[str] | None,
    parent_session_id: str | None = None,
) -> dict[str, str]:
    """Build the equality filter map for store.query()."""
    filters: dict[str, str] = {}
    if workflow_id:
        filters["workflow_id"] = workflow_id
    if status_filter and not statuses:
        filters["status"] = status_filter
    if parent_session_id:
        filters["parent_session_id"] = parent_session_id
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
        data = [
            d for d in data if within_window(d.get("started_at"), started_after, started_before)
        ]
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
    launch = AgentLaunch.read(event_data.get("agent_launch"))
    if launch is not AgentLaunch.UNKNOWN:
        # A completion event written before this field existed says nothing,
        # so it must leave the row as it found it. Overwriting with UNKNOWN
        # would be harmless today and wrong the moment a live AgentLaunched
        # has already landed on the row (#1047, #1065).
        existing["agent_launch"] = launch.value


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
    VERSION = 4  # Bumped: agent_launch fact for never-started detection (#1047, #1065)

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
            parent_session_id=event_data.get("parent_session_id"),
            root_session_id=event_data.get("root_session_id"),
            repos=tuple(event_data.get("repos", ())),
            agent_launch=AgentLaunch.UNKNOWN,
        )
        await self._store.save(self.PROJECTION_NAME, session_id, summary.to_dict())

    async def on_agent_launched(self, event_data: dict) -> None:
        """Handle AgentLaunched - an agent process exists for this session.

        Makes the fact visible while the session is still running. The
        durable answer arrives again on SessionCompleted, which is what a
        terminal session is read from (#1047, #1065).
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            existing["agent_launch"] = AgentLaunch.LAUNCHED.value
            await self._store.save(self.PROJECTION_NAME, session_id, existing)

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
        parent_session_id: str | None = None,
    ) -> list[SessionSummary]:
        """Query sessions with optional filtering.

        ``statuses`` (multi-select) takes precedence over ``status_filter``
        (single value, kept for backwards compatibility).

        Time-range filters (``started_after`` / ``started_before``) are applied
        post-fetch in Python because the underlying store filter only supports
        equality. We fetch without a row cap when bounds are present so the
        bounded slice is honoured even on installs with many sessions.

        ``parent_session_id`` restricts results to sessions delegated by that
        session (issue #792); it is an equality filter handled by the store.
        """
        filters = _build_query_filters(workflow_id, status_filter, statuses, parent_session_id)
        post_filtering = bool(statuses or started_after is not None or started_before is not None)
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
            data = _apply_post_filters(data, statuses, started_after, started_before, offset, limit)

        return [SessionSummary.from_dict(d) for d in data]

    async def page(
        self,
        *,
        workflow_id: str | None = None,
        parent_session_id: str | None = None,
        statuses: Collection[str] | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Page[SessionSummary]:
        """One page of sessions, with the total and status facets it came from.

        ``query`` answers "which rows", which was enough while the endpoint had
        no paging: it capped at 200 and there was nowhere to go from there, so
        roughly a day of history was reachable and the rest was not addressable
        at any parameter setting. Paging needs a total counted over the same
        predicate as the rows, which is what this returns.

        Only the equality filters the store can express are pushed down.
        ``status`` deliberately is NOT, even though the store could: the facet
        tally has to see every status the rest of the query matched, and a
        store-side status filter would leave it able to report only the one
        already selected.

        ``search`` matches case-insensitively against the session id and the
        workflow id.
        """
        filters = _build_query_filters(workflow_id, None, None, parent_session_id)

        def base(record: Mapping[str, object]) -> bool:
            return within_window(
                record.get("started_at"), started_after, started_before
            ) and matches_search(search, record.get("id"), record.get("workflow_id"))

        return paginate(
            await self._store.query(
                self.PROJECTION_NAME,
                filters=filters if filters else None,
                order_by="-started_at",
                limit=None,
                offset=0,
            ),
            base_predicate=base,
            status_of=lambda r: str(r.get("status") or ""),
            statuses=statuses,
            sort_key=lambda r: str(r.get("started_at") or ""),
            to_row=SessionSummary.from_dict,
            offset=offset,
            limit=limit,
        )

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
