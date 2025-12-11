"""Workspace event emission for observability.

Emits workspace lifecycle events to the event store for:
- Performance monitoring
- Debugging
- Analytics dashboards

Events can be consumed by the WorkspaceMetricsProjection.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from aef_adapters.workspaces.config import IsolatedWorkspaceConfig
    from aef_adapters.workspaces.protocol import IsolatedWorkspace

logger = logging.getLogger(__name__)


class EventEmitter(Protocol):
    """Protocol for emitting domain events."""

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event.

        Args:
            event_type: Type of event (e.g., "WorkspaceCreated")
            data: Event payload
        """
        ...


@dataclass
class WorkspaceEventEmitter:
    """Emits workspace lifecycle events.

    Can use different backends:
    - LoggingEmitter (default): Logs events for debugging
    - CollectorEmitter: Posts to aef-collector service
    - DirectEmitter: Writes directly to event store

    Usage:
        emitter = WorkspaceEventEmitter()
        await emitter.workspace_creating(config, workspace_id)
        # ... create workspace ...
        await emitter.workspace_created(workspace, duration_ms)
    """

    emitter: EventEmitter | None = None
    enabled: bool = True

    # Track timing for duration calculations
    _create_start_times: dict[str, float] = field(default_factory=dict)

    async def workspace_creating(
        self,
        config: IsolatedWorkspaceConfig,
        workspace_id: str,
    ) -> None:
        """Emit WorkspaceCreating event when creation starts."""
        if not self.enabled:
            return

        self._create_start_times[workspace_id] = time.perf_counter()

        await self._emit(
            "WorkspaceCreating",
            {
                "workspace_id": workspace_id,
                "session_id": config.base_config.session_id,
                "workflow_id": getattr(config.base_config, "workflow_id", None),
                "execution_id": getattr(config.base_config, "execution_id", None),
                "isolation_backend": config.isolation_backend.value
                if config.isolation_backend
                else "unknown",
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

    async def workspace_created(
        self,
        workspace: IsolatedWorkspace,
        config: IsolatedWorkspaceConfig,
    ) -> None:
        """Emit WorkspaceCreated event when workspace is ready."""
        if not self.enabled:
            return

        workspace_id = getattr(workspace, "container_id", None) or str(uuid.uuid4())[:8]
        start_time = self._create_start_times.pop(workspace_id, None)
        duration_ms = (time.perf_counter() - start_time) * 1000 if start_time else 0

        await self._emit(
            "WorkspaceCreated",
            {
                "workspace_id": workspace_id,
                "session_id": config.base_config.session_id,
                "workflow_id": getattr(config.base_config, "workflow_id", None),
                "execution_id": getattr(config.base_config, "execution_id", None),
                "isolation_backend": workspace.isolation_backend.value,
                "container_id": workspace.container_id,
                "created_at": datetime.now(UTC).isoformat(),
                "create_duration_ms": duration_ms,
                "workspace_path": str(workspace.path),
            },
        )

    async def workspace_command_executed(
        self,
        workspace: IsolatedWorkspace,
        command: list[str],
        exit_code: int,
        duration_ms: float,
        stdout_lines: int = 0,
        stderr_lines: int = 0,
    ) -> None:
        """Emit WorkspaceCommandExecuted event."""
        if not self.enabled:
            return

        workspace_id = getattr(workspace, "container_id", None) or "unknown"

        await self._emit(
            "WorkspaceCommandExecuted",
            {
                "workspace_id": workspace_id,
                "session_id": workspace.config.session_id,
                "command": command,
                "exit_code": exit_code,
                "success": exit_code == 0,
                "duration_ms": duration_ms,
                "stdout_lines": stdout_lines,
                "stderr_lines": stderr_lines,
                "executed_at": datetime.now(UTC).isoformat(),
            },
        )

    async def workspace_destroying(
        self,
        workspace: IsolatedWorkspace,
    ) -> None:
        """Emit WorkspaceDestroying event."""
        if not self.enabled:
            return

        workspace_id = getattr(workspace, "container_id", None) or "unknown"
        self._create_start_times[f"destroy_{workspace_id}"] = time.perf_counter()

        await self._emit(
            "WorkspaceDestroying",
            {
                "workspace_id": workspace_id,
                "session_id": workspace.config.session_id,
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

    async def workspace_destroyed(
        self,
        workspace: IsolatedWorkspace,
        total_lifetime_ms: float,
        commands_executed: int = 0,
        artifacts_collected: int = 0,
    ) -> None:
        """Emit WorkspaceDestroyed event."""
        if not self.enabled:
            return

        workspace_id = getattr(workspace, "container_id", None) or "unknown"
        destroy_start = self._create_start_times.pop(f"destroy_{workspace_id}", None)
        destroy_duration_ms = (time.perf_counter() - destroy_start) * 1000 if destroy_start else 0

        await self._emit(
            "WorkspaceDestroyed",
            {
                "workspace_id": workspace_id,
                "session_id": workspace.config.session_id,
                "destroyed_at": datetime.now(UTC).isoformat(),
                "destroy_duration_ms": destroy_duration_ms,
                "total_lifetime_ms": total_lifetime_ms,
                "commands_executed": commands_executed,
                "artifacts_collected": artifacts_collected,
            },
        )

    async def workspace_error(
        self,
        workspace_id: str,
        session_id: str,
        operation: str,
        error: Exception,
        isolation_backend: str | None = None,
    ) -> None:
        """Emit WorkspaceError event."""
        if not self.enabled:
            return

        await self._emit(
            "WorkspaceError",
            {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "operation": operation,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "isolation_backend": isolation_backend,
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event through the configured emitter."""
        if self.emitter:
            try:
                await self.emitter.emit(event_type, data)
            except Exception as e:
                logger.warning(f"Failed to emit {event_type}: {e}")
        else:
            # Default: log for debugging
            logger.debug(f"Workspace event: {event_type} - {data}")


class LoggingEmitter:
    """Emitter that logs events for debugging."""

    def __init__(self, level: int = logging.DEBUG):
        self.level = level
        self.logger = logging.getLogger(__name__)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Log the event."""
        self.logger.log(self.level, f"[WORKSPACE_EVENT] {event_type}: {data}")


# Global emitter instance (can be configured at startup)
_global_emitter: WorkspaceEventEmitter | None = None


def get_workspace_emitter() -> WorkspaceEventEmitter:
    """Get the global workspace event emitter.

    Creates a default emitter if not configured.
    """
    global _global_emitter
    if _global_emitter is None:
        _global_emitter = WorkspaceEventEmitter()
    return _global_emitter


def configure_workspace_emitter(
    emitter: EventEmitter | None = None,
    enabled: bool = True,
) -> None:
    """Configure the global workspace event emitter.

    Args:
        emitter: EventEmitter implementation to use
        enabled: Whether to emit events
    """
    global _global_emitter
    _global_emitter = WorkspaceEventEmitter(emitter=emitter, enabled=enabled)
