"""Subagent lifecycle tracker for workflow execution.

Tracks Task tool (subagent) start/stop events and tool name resolution.
Extracted from WorkflowExecutionEngine per ADR-037.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

# Any: input_data comes from json.loads() (external CLI JSONL — system boundary)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubagentLifecycleRecord:
    """Represents a subagent lifecycle event."""

    agent_name: str
    tool_use_id: str
    event_type: Literal["started", "stopped"]
    duration_ms: int | None = None
    success: bool | None = None
    tools_used: dict[str, int] | None = None
    model: str | None = None  # ISS-269: model the subagent runs on (from agent definition)


class SubagentTracker:
    """Tracks active subagents (Task tool) and tool name resolution.

    Owns two pieces of state:
    - Active subagents: tool_use_id → (agent_name, started_at, tools_used)
    - Tool name cache: tool_use_id → tool_name (for enriching tool_result events)
    """

    def __init__(self) -> None:
        # active: tool_use_id → (agent_name, started_at, tools_used, model)
        self._active: dict[str, tuple[str, datetime, dict[str, int], str | None]] = {}
        self._tool_names_cache: dict[str, str] = {}

    def register_tool_use(self, tool_use_id: str, tool_name: str) -> None:
        """Cache a tool_use_id → tool_name mapping for later resolution."""
        self._tool_names_cache[tool_use_id] = tool_name

    def resolve_tool_name(self, tool_use_id: str) -> str:
        """Resolve tool_use_id to tool_name. Returns 'unknown' if not cached."""
        return self._tool_names_cache.get(tool_use_id, "unknown")

    def on_task_started(
        self, tool_use_id: str, input_data: dict[str, Any]
    ) -> SubagentLifecycleRecord:
        """Record a Task tool starting (subagent spawn).

        Args:
            tool_use_id: The tool_use_id of the Task tool call
            input_data: Parsed input data (may contain subagent_type or description)

        Returns:
            SubagentLifecycleRecord with event_type="started"
        """
        agent_name = str(input_data.get("subagent_type", input_data.get("description", "unknown")))[
            :50
        ]
        model = input_data.get("model") or None  # populated once ISS-270 wires --agents
        self._active[tool_use_id] = (agent_name, datetime.now(UTC), {}, model)
        return SubagentLifecycleRecord(
            agent_name=agent_name,
            tool_use_id=tool_use_id,
            event_type="started",
            model=model,
        )

    def on_task_started_from_hook(
        self, tool_use_id: str, input_preview: str
    ) -> SubagentLifecycleRecord:
        """Record a Task tool starting from hook event format.

        Args:
            tool_use_id: The tool_use_id
            input_preview: JSON string of the input preview

        Returns:
            SubagentLifecycleRecord with event_type="started"
        """
        agent_name = "unknown"
        model: str | None = None
        if input_preview:
            try:
                input_data = json.loads(input_preview)
                agent_name = str(
                    input_data.get("subagent_type", input_data.get("description", "unknown"))
                )[:50]
                model = input_data.get("model") or None
            except (json.JSONDecodeError, TypeError):
                pass
        self._active[tool_use_id] = (agent_name, datetime.now(UTC), {}, model)
        return SubagentLifecycleRecord(
            agent_name=agent_name,
            tool_use_id=tool_use_id,
            event_type="started",
            model=model,
        )

    def on_task_completed(self, tool_use_id: str, success: bool) -> SubagentLifecycleRecord | None:
        """Record a Task tool completing (subagent stop).

        Args:
            tool_use_id: The tool_use_id of the completed Task
            success: Whether the task completed successfully

        Returns:
            SubagentLifecycleRecord with event_type="stopped", or None if no matching active subagent
        """
        if tool_use_id not in self._active:
            return None
        agent_name, started_at, tools_used, model = self._active.pop(tool_use_id)
        duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        return SubagentLifecycleRecord(
            agent_name=agent_name,
            tool_use_id=tool_use_id,
            event_type="stopped",
            duration_ms=duration_ms,
            success=success,
            tools_used=tools_used,
            model=model,
        )

    def attribute_tool(self, tool_name: str) -> None:
        """Attribute a tool call to the most recently started subagent."""
        if not self._active or not tool_name:
            return
        latest_id = max(
            self._active.keys(),
            key=lambda k: self._active[k][1],  # Sort by started_at
        )
        _, _, tools_dict, _ = self._active[latest_id]
        tools_dict[tool_name] = tools_dict.get(tool_name, 0) + 1

    @property
    def has_active(self) -> bool:
        """Whether there are any active subagents."""
        return len(self._active) > 0
