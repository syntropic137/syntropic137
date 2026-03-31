"""Result type and shared Pydantic models for the Syn137 API.

Provides a discriminated union Result type for typed error handling,
plus Pydantic response models used across all v1 modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 — needed at runtime for Pydantic
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):  # noqa: UP046 — Generic required for @dataclass(slots=True)
    """Success variant of Result."""

    value: T


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):  # noqa: UP046 — Generic required for @dataclass(slots=True)
    """Error variant of Result."""

    error: E
    message: str | None = None


Result = Ok[T] | Err[E]

# ---------------------------------------------------------------------------
# Error enums
# ---------------------------------------------------------------------------


class WorkflowError(str, Enum):
    """Errors returned by workflow operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_ARCHIVED = "already_archived"
    INVALID_INPUT = "invalid_input"
    EXECUTION_FAILED = "execution_failed"
    HAS_ACTIVE_EXECUTIONS = "has_active_executions"
    NOT_IMPLEMENTED = "not_implemented"


class ExecutionError(str, Enum):
    """Errors returned by execution operations."""

    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    EXECUTION_FAILED = "execution_failed"
    SIGNAL_FAILED = "signal_failed"


class MetricsError(str, Enum):
    """Errors returned by metrics operations."""

    QUERY_FAILED = "query_failed"
    NOT_FOUND = "not_found"


class LifecycleError(str, Enum):
    """Errors returned by lifecycle operations."""

    CONNECTION_FAILED = "connection_failed"
    VALIDATION_FAILED = "validation_failed"


class SessionError(str, Enum):
    """Errors returned by session operations."""

    NOT_FOUND = "not_found"
    ALREADY_COMPLETED = "already_completed"
    INVALID_INPUT = "invalid_input"
    NOT_IMPLEMENTED = "not_implemented"


class ArtifactError(str, Enum):
    """Errors returned by artifact operations."""

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    STORAGE_ERROR = "storage_error"
    NOT_IMPLEMENTED = "not_implemented"
    ALREADY_DELETED = "already_deleted"


class GitHubError(str, Enum):
    """Errors returned by GitHub operations."""

    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    INVALID_SIGNATURE = "invalid_signature"
    INVALID_PAYLOAD = "invalid_payload"
    PROCESSING_FAILED = "processing_failed"
    NOT_IMPLEMENTED = "not_implemented"


class ObservabilityError(str, Enum):
    """Errors returned by observability operations."""

    NOT_FOUND = "not_found"
    QUERY_FAILED = "query_failed"
    NOT_IMPLEMENTED = "not_implemented"


class TriggerError(str, Enum):
    """Errors returned by trigger operations."""

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    ALREADY_PAUSED = "already_paused"
    ALREADY_ACTIVE = "already_active"
    ALREADY_DELETED = "already_deleted"
    PRESET_NOT_FOUND = "preset_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"


class OrganizationError(str, Enum):
    """Errors returned by organization operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_DELETED = "already_deleted"
    INVALID_INPUT = "invalid_input"
    HAS_SYSTEMS = "has_systems"
    HAS_REPOS = "has_repos"


class SystemErrorCode(str, Enum):
    """Errors returned by system operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_DELETED = "already_deleted"
    INVALID_INPUT = "invalid_input"
    ORGANIZATION_NOT_FOUND = "organization_not_found"
    HAS_REPOS = "has_repos"


class RepoError(str, Enum):
    """Errors returned by repo operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    INVALID_INPUT = "invalid_input"
    ORGANIZATION_NOT_FOUND = "organization_not_found"
    SYSTEM_NOT_FOUND = "system_not_found"
    ALREADY_ASSIGNED = "already_assigned"
    NOT_ASSIGNED = "not_assigned"
    ALREADY_DEREGISTERED = "already_deregistered"
    HAS_ACTIVE_TRIGGERS = "has_active_triggers"


class AgentError(str, Enum):
    """Errors returned by agent operations."""

    PROVIDER_NOT_FOUND = "provider_not_found"
    API_KEY_MISSING = "api_key_missing"
    COMPLETION_FAILED = "completion_failed"


class ConfigError(str, Enum):
    """Errors returned by config operations."""

    LOAD_FAILED = "load_failed"


# ---------------------------------------------------------------------------
# Response models — Pydantic schemas for API consumers
# ---------------------------------------------------------------------------


class WorkflowSummary(BaseModel):
    """Summary of a workflow template for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    workflow_type: str
    classification: str
    phase_count: int
    description: str | None = None
    created_at: datetime | None = None
    runs_count: int = 0
    is_archived: bool = False


class InputDeclarationResponse(BaseModel):
    """Input declaration within a workflow template."""

    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None


class PhaseDefinitionResponse(BaseModel):
    """Phase definition within a workflow template."""

    phase_id: str
    name: str
    order: int = 0
    description: str | None = None
    agent_type: str = ""
    prompt_template: str | None = None
    timeout_seconds: int = 300
    allowed_tools: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    model: str | None = None


class WorkflowDetail(BaseModel):
    """Detailed workflow template response."""

    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinitionResponse] = Field(default_factory=list)
    input_declarations: list[InputDeclarationResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    runs_count: int = 0


class ExecutionSummary(BaseModel):
    """Summary of a workflow execution run."""

    model_config = ConfigDict(from_attributes=True)

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal | str = Decimal("0")
    tool_call_count: int = 0
    error_message: str | None = None


class ExecutionDetail(BaseModel):
    """Detailed workflow execution response."""

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: Decimal | str = Decimal("0")
    total_duration_seconds: float = 0.0
    artifact_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


class SessionSummary(BaseModel):
    """Summary of an agent session."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    status: str = ""
    agent_type: str = ""
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ArtifactSummary(BaseModel):
    """Summary of an artifact."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str | None = None
    phase_id: str | None = None
    artifact_type: str = ""
    title: str | None = None
    size_bytes: int = 0
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Organization models
# ---------------------------------------------------------------------------


class OrganizationSummaryResponse(BaseModel):
    """Summary of an organization for list views."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: str
    name: str
    slug: str
    created_by: str = ""
    created_at: datetime | None = None
    system_count: int = 0
    repo_count: int = 0


class SystemSummaryResponse(BaseModel):
    """Summary of a system for list views."""

    model_config = ConfigDict(from_attributes=True)

    system_id: str
    organization_id: str
    name: str
    description: str = ""
    created_by: str = ""
    created_at: datetime | None = None
    repo_count: int = 0


class RepoSummaryResponse(BaseModel):
    """Summary of a repo for list views."""

    model_config = ConfigDict(from_attributes=True)

    repo_id: str
    organization_id: str
    system_id: str = ""
    provider: str = "github"
    full_name: str = ""
    owner: str = ""
    default_branch: str = "main"
    installation_id: str = ""
    is_private: bool = False
    created_by: str = ""
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Trigger models
# ---------------------------------------------------------------------------


class TriggerSummary(BaseModel):
    """Summary of a trigger rule for list views."""

    model_config = ConfigDict(from_attributes=True)

    trigger_id: str
    name: str
    event: str
    repository: str
    workflow_id: str
    status: str
    fire_count: int = 0
    created_at: datetime | None = None


class TriggerDetail(BaseModel):
    """Detailed trigger rule response."""

    trigger_id: str
    name: str
    event: str
    repository: str
    workflow_id: str
    status: str
    fire_count: int = 0
    created_at: datetime | None = None
    conditions: list[dict] = Field(default_factory=list)
    input_mapping: dict[str, str] = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    installation_id: str = ""
    created_by: str = ""
    last_fired_at: datetime | None = None


class TriggerHistoryEntry(BaseModel):
    """A single entry in a trigger's execution history."""

    trigger_id: str
    execution_id: str
    webhook_delivery_id: str = ""
    github_event_type: str = ""
    repository: str = ""
    pr_number: int | None = None
    fired_at: datetime | None = None
    status: str = "dispatched"
    cost_usd: float | None = None


# ---------------------------------------------------------------------------
# Agent models
# ---------------------------------------------------------------------------


class AgentProviderInfo(BaseModel):
    """Information about an available agent provider."""

    provider: str
    display_name: str
    available: bool
    default_model: str


class AgentTestResult(BaseModel):
    """Result of testing an agent provider."""

    provider: str
    model: str
    response_text: str
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class ConfigSnapshot(BaseModel):
    """Snapshot of the current application configuration."""

    app: dict = Field(default_factory=dict)
    database: dict = Field(default_factory=dict)
    agents: dict = Field(default_factory=dict)
    storage: dict = Field(default_factory=dict)


class ConfigIssue(BaseModel):
    """A configuration issue found during validation."""

    level: str  # "error" | "warning" | "info"
    category: str
    message: str


# ---------------------------------------------------------------------------
# Workflow validation model
# ---------------------------------------------------------------------------


class WorkflowValidation(BaseModel):
    """Result of validating a workflow YAML file."""

    valid: bool
    name: str | None = None
    workflow_type: str | None = None
    phase_count: int = 0
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Execution detail models
# ---------------------------------------------------------------------------


class ToolOperation(BaseModel):
    """A single timeline event within a session.

    Covers tool executions, git operations, subagent lifecycle, and other
    observability events. Use operation_type to distinguish categories.
    """

    model_config = ConfigDict(from_attributes=True)

    observation_id: str = ""
    operation_type: str = ""
    timestamp: datetime | None = None
    duration_ms: float | None = None
    success: bool | None = None
    # Tool-specific fields
    tool_name: str | None = None
    tool_use_id: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    # Git-specific fields (populated for git_commit, git_push, git_branch_changed, git_operation)
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None


class PhaseExecution(BaseModel):
    """Detailed phase execution with tool operations."""

    phase_id: str
    name: str
    status: str
    session_id: str | None = None
    artifact_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_seconds: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    operations: list[ToolOperation] = Field(default_factory=list)


class ExecutionDetailFull(BaseModel):
    """Rich execution detail with phases and tool operations."""

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    phases: list[PhaseExecution] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: Decimal | str = Decimal("0")
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    error_message: str | None = None


class ControlResult(BaseModel):
    """Result of a control command (pause/resume/cancel/inject)."""

    success: bool
    execution_id: str
    new_state: str
    message: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Session detail model
# ---------------------------------------------------------------------------


class SessionDetail(BaseModel):
    """Detailed session with tool operations and cost data."""

    id: str
    workflow_id: str | None = None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    agent_type: str = ""
    status: str = ""
    workspace_path: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    agent_model: str | None = None
    operations: list[ToolOperation] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None


# ---------------------------------------------------------------------------
# Artifact detail model
# ---------------------------------------------------------------------------


class ArtifactDetail(BaseModel):
    """Detailed artifact with optional content."""

    id: str
    workflow_id: str | None = None
    phase_id: str | None = None
    session_id: str | None = None
    artifact_type: str = ""
    title: str | None = None
    content: str | None = None
    content_type: str | None = None
    content_hash: str | None = None
    size_bytes: int = 0
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Metrics + Cost models (merged)
# ---------------------------------------------------------------------------


class DashboardMetrics(BaseModel):
    """Aggregated dashboard metrics."""

    total_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_sessions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_artifacts: int = 0
    total_artifact_bytes: int = 0


class SessionCostData(BaseModel):
    """Cost data for a single session."""

    session_id: str
    execution_id: str | None = None
    workflow_id: str | None = None
    phase_id: str | None = None
    total_cost_usd: Decimal = Decimal("0")
    token_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    duration_ms: int = 0
    cost_by_model: dict = Field(default_factory=dict)
    cost_by_tool: dict = Field(default_factory=dict)
    is_finalized: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExecutionCostData(BaseModel):
    """Cost data for an execution."""

    execution_id: str
    workflow_id: str | None = None
    session_count: int = 0
    session_ids: list[str] = Field(default_factory=list)
    total_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_by_phase: dict = Field(default_factory=dict)
    cost_by_model: dict = Field(default_factory=dict)
    cost_by_tool: dict = Field(default_factory=dict)
    is_complete: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CostSummary(BaseModel):
    """Overall cost summary across all executions."""

    total_cost_usd: Decimal = Decimal("0")
    total_sessions: int = 0
    total_executions: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    top_models: list[dict] = Field(default_factory=list)
    top_sessions: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Events / Observability models
# ---------------------------------------------------------------------------


class EventRecord(BaseModel):
    """A single event from the event store."""

    time: datetime | None = None
    event_type: str = ""
    session_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    data: dict = Field(default_factory=dict)


class TimelineEntry(BaseModel):
    """A timeline entry for session tool usage."""

    time: datetime | None = None
    event_type: str = ""
    tool_name: str | None = None
    duration_ms: float | None = None
    success: bool | None = None


class ToolUsageSummary(BaseModel):
    """Summary of tool usage across a session."""

    tool_name: str
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Conversation models
# ---------------------------------------------------------------------------


class ConversationLine(BaseModel):
    """A single line from a conversation log."""

    line_number: int
    raw: str
    event_type: str | None = None
    tool_name: str | None = None
    content_preview: str | None = None


class ConversationLog(BaseModel):
    """Full conversation log for a session."""

    session_id: str
    lines: list[ConversationLine] = Field(default_factory=list)
    total_lines: int = 0
    metadata: dict | None = None


class ConversationMeta(BaseModel):
    """Conversation metadata without full log content."""

    session_id: str
    event_count: int = 0
    model: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    tool_counts: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# GitHub webhook model
# ---------------------------------------------------------------------------


class WebhookResult(BaseModel):
    """Result of processing a GitHub webhook."""

    status: str
    event: str
    triggers_fired: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Realtime model
# ---------------------------------------------------------------------------


class RealtimeHealth(BaseModel):
    """Health status of the realtime projection."""

    active_executions: int = 0
    active_connections: int = 0
