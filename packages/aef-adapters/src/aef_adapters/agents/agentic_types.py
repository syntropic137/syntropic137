"""Agentic types - data structures for agentic task execution.

These types support the agentic execution paradigm where agents:
- Execute tasks autonomously until completion
- Use tools (Read, Write, Bash, Edit, etc.)
- Stream events as they work
- Control their own execution flow

This is fundamentally different from the chat completion model in protocol.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from aef_shared import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT


class AgentTool(str, Enum):
    """Standard tools available to agentic agents.

    These map to tools provided by agentic SDKs like claude-agent-sdk.
    """

    # File operations
    READ = "Read"
    WRITE = "Write"
    EDIT = "Edit"
    MULTI_EDIT = "MultiEdit"

    # Directory operations
    LS = "LS"
    GLOB = "Glob"
    GREP = "Grep"

    # Execution
    BASH = "Bash"

    # Task management
    TODO_READ = "TodoRead"
    TODO_WRITE = "TodoWrite"

    # Web operations (when available)
    WEB_SEARCH = "WebSearch"
    WEB_FETCH = "WebFetch"

    @classmethod
    def all(cls) -> set[str]:
        """Get all tool names as strings."""
        return {tool.value for tool in cls}

    @classmethod
    def file_tools(cls) -> set[str]:
        """Get file operation tools."""
        return {cls.READ.value, cls.WRITE.value, cls.EDIT.value, cls.MULTI_EDIT.value}

    @classmethod
    def safe_tools(cls) -> set[str]:
        """Get read-only tools (safe for exploration)."""
        return {cls.READ.value, cls.LS.value, cls.GLOB.value, cls.GREP.value, cls.TODO_READ.value}


@dataclass(frozen=True)
class AgentExecutionConfig:
    """Configuration for agentic task execution.

    Controls how an agent executes a task, including which tools
    it can use, resource limits, and behavior options.
    """

    # Tool permissions
    allowed_tools: frozenset[str] = field(default_factory=lambda: frozenset(AgentTool.all()))

    # Execution limits
    max_turns: int = 25
    max_budget_usd: float | None = None
    timeout_seconds: int = 600  # 10 minutes default

    # Behavior
    permission_mode: str = "bypassPermissions"  # For automated execution
    system_prompt: str | None = None

    # Context sources for hooks
    setting_sources: tuple[str, ...] = ("project",)

    def with_tools(self, tools: set[str]) -> AgentExecutionConfig:
        """Create new config with specified tools."""
        return AgentExecutionConfig(
            allowed_tools=frozenset(tools),
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            timeout_seconds=self.timeout_seconds,
            permission_mode=self.permission_mode,
            system_prompt=self.system_prompt,
            setting_sources=self.setting_sources,
        )

    def with_budget(self, max_usd: float) -> AgentExecutionConfig:
        """Create new config with budget limit."""
        return AgentExecutionConfig(
            allowed_tools=self.allowed_tools,
            max_turns=self.max_turns,
            max_budget_usd=max_usd,
            timeout_seconds=self.timeout_seconds,
            permission_mode=self.permission_mode,
            system_prompt=self.system_prompt,
            setting_sources=self.setting_sources,
        )


# ============================================================================
# Agent Events - streamed during task execution
# ============================================================================


@dataclass(frozen=True)
class ToolUseStarted:
    """Agent started using a tool.

    Emitted when the agent invokes a tool, before execution completes.
    """

    event_type: str = field(default="tool_use_started", init=False)
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_use_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ToolUseCompleted:
    """Agent completed using a tool.

    Emitted after tool execution finishes (successfully or not).
    """

    event_type: str = field(default="tool_use_completed", init=False)
    tool_name: str = ""
    tool_use_id: str | None = None
    tool_output: str | None = None
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ToolBlocked:
    """Tool use was blocked by a security hook.

    Emitted when a validator in the hook pipeline blocks a tool call.
    """

    event_type: str = field(default="tool_blocked", init=False)
    tool_name: str = ""
    tool_use_id: str | None = None
    reason: str = ""
    validator: str | None = None  # Which validator blocked it
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ThinkingUpdate:
    """Agent thinking/reasoning update.

    Optional streaming of agent's internal reasoning (when available).
    """

    event_type: str = field(default="thinking_update", init=False)
    content: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class TextOutput:
    """Agent produced text output (not a tool call).

    Streaming text content from the agent.
    """

    event_type: str = field(default="text_output", init=False)
    content: str = ""
    is_partial: bool = True  # True if more content coming
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class TurnCompleted:
    """Agent completed a turn (one API round-trip).

    Emitted after each AssistantMessage with per-turn token usage.
    This enables live token streaming during execution.
    """

    event_type: str = field(default="turn_completed", init=False)
    turn_number: int = 0

    # Per-turn token usage
    input_tokens: int = 0
    output_tokens: int = 0

    # Cumulative totals so far
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class TaskCompleted:
    """Agent completed the task.

    Final event indicating successful task completion.
    """

    event_type: str = field(default="task_completed", init=False)
    result: str = ""

    # Usage metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # Execution stats
    turns_used: int = 0
    tools_used: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    # Cost estimate
    estimated_cost_usd: float | None = None

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class TaskFailed:
    """Agent failed to complete the task.

    Final event indicating task failure.
    """

    event_type: str = field(default="task_failed", init=False)
    error: str = ""
    error_type: str | None = None  # e.g., "timeout", "budget_exceeded", "api_error"
    partial_result: str | None = None  # Any output before failure

    # Usage metrics (up to failure)
    input_tokens: int = 0
    output_tokens: int = 0
    turns_used: int = 0
    duration_ms: float = 0.0

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# Union type for all agent events
AgentEvent = (
    ToolUseStarted
    | ToolUseCompleted
    | ToolBlocked
    | ThinkingUpdate
    | TextOutput
    | TurnCompleted
    | TaskCompleted
    | TaskFailed
)


# ============================================================================
# Workspace Types
# ============================================================================


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for creating an agent workspace.

    Workspaces provide isolated execution environments with
    pre-configured hooks from agentic-primitives.
    """

    session_id: str
    base_dir: Path = field(default_factory=lambda: Path.cwd() / ".workspaces")

    # Optional identifiers for correlation
    workflow_id: str | None = None
    phase_id: str | None = None

    # Hook configuration
    hooks_source: Path | None = None  # Defaults to agentic-primitives
    analytics_path: str = ".agentic/analytics/events.jsonl"

    # Cleanup behavior
    cleanup_on_exit: bool = True


@dataclass
class Workspace:
    """An active agent workspace.

    Represents an isolated directory where an agent executes,
    with hooks configured and context injected.
    """

    path: Path
    config: WorkspaceConfig

    @property
    def analytics_path(self) -> Path:
        """Path to the analytics events file."""
        return self.path / self.config.analytics_path

    @property
    def context_dir(self) -> Path:
        """Directory for injected context files."""
        return self.path / ".context"

    @property
    def output_dir(self) -> Path:
        """Directory for agent outputs (artifacts)."""
        rel_path = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT)
        return self.path / str(rel_path)

    @property
    def hooks_dir(self) -> Path:
        """Directory containing hook handlers."""
        return self.path / ".claude" / "hooks"


# ============================================================================
# Execution Result
# ============================================================================


@dataclass
class AgentExecutionResult:
    """Complete result of an agentic task execution.

    Aggregates all events and provides summary metrics.
    """

    # Task identification
    task: str
    session_id: str

    # Final state
    success: bool
    result: str
    error: str | None = None

    # All events captured
    events: list[AgentEvent] = field(default_factory=list)

    # Aggregated metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    duration_ms: float = 0.0
    turns_used: int = 0

    # Tool usage summary
    tools_used: dict[str, int] = field(default_factory=dict)  # tool_name -> count
    tools_blocked: list[str] = field(default_factory=list)

    @property
    def tool_call_count(self) -> int:
        """Total number of tool calls."""
        return sum(self.tools_used.values())

    def add_event(self, event: AgentEvent) -> None:
        """Add an event and update aggregated metrics."""
        self.events.append(event)

        if isinstance(event, ToolUseCompleted):
            self.tools_used[event.tool_name] = self.tools_used.get(event.tool_name, 0) + 1
        elif isinstance(event, ToolBlocked):
            self.tools_blocked.append(event.tool_name)
        elif isinstance(event, TaskCompleted):
            self.success = True
            self.result = event.result
            self.input_tokens = event.input_tokens
            self.output_tokens = event.output_tokens
            self.total_tokens = event.total_tokens
            self.estimated_cost_usd = event.estimated_cost_usd or 0.0
            self.duration_ms = event.duration_ms
            self.turns_used = event.turns_used
        elif isinstance(event, TaskFailed):
            self.success = False
            self.error = event.error
            self.input_tokens = event.input_tokens
            self.output_tokens = event.output_tokens
            self.duration_ms = event.duration_ms
            self.turns_used = event.turns_used
