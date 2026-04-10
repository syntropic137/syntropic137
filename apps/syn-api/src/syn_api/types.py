"""Result type and shared Pydantic models for the Syn137 API.

Provides a discriminated union Result type for typed error handling,
plus Pydantic response models used across all v1 modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 — needed at runtime for Pydantic
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Literal, TypeVar

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


class WorkflowError(StrEnum):
    """Errors returned by workflow operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_ARCHIVED = "already_archived"
    INVALID_INPUT = "invalid_input"
    EXECUTION_FAILED = "execution_failed"
    HAS_ACTIVE_EXECUTIONS = "has_active_executions"
    NOT_IMPLEMENTED = "not_implemented"


class ExecutionError(StrEnum):
    """Errors returned by execution operations."""

    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    EXECUTION_FAILED = "execution_failed"
    SIGNAL_FAILED = "signal_failed"


class MetricsError(StrEnum):
    """Errors returned by metrics operations."""

    QUERY_FAILED = "query_failed"
    NOT_FOUND = "not_found"


class LifecycleError(StrEnum):
    """Errors returned by lifecycle operations."""

    CONNECTION_FAILED = "connection_failed"
    VALIDATION_FAILED = "validation_failed"


class SessionError(StrEnum):
    """Errors returned by session operations."""

    NOT_FOUND = "not_found"
    ALREADY_COMPLETED = "already_completed"
    INVALID_INPUT = "invalid_input"
    NOT_IMPLEMENTED = "not_implemented"


class ArtifactError(StrEnum):
    """Errors returned by artifact operations."""

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    STORAGE_ERROR = "storage_error"
    NOT_IMPLEMENTED = "not_implemented"
    ALREADY_DELETED = "already_deleted"


class GitHubError(StrEnum):
    """Errors returned by GitHub operations."""

    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    INVALID_SIGNATURE = "invalid_signature"
    INVALID_PAYLOAD = "invalid_payload"
    PROCESSING_FAILED = "processing_failed"
    NOT_IMPLEMENTED = "not_implemented"


# ---------------------------------------------------------------------------
# GitHub accessible repo models
# ---------------------------------------------------------------------------


class GitHubRepoResponse(BaseModel):
    """A repository accessible to the GitHub App installation."""

    model_config = ConfigDict(from_attributes=True)

    github_id: int
    name: str
    full_name: str
    private: bool
    default_branch: str
    owner: str
    installation_id: str


class GitHubRepoListResponse(BaseModel):
    """List of repositories accessible to the GitHub App."""

    repos: list[GitHubRepoResponse] = Field(default_factory=list)
    total: int = 0
    installation_id: str | None = None


class ObservabilityError(StrEnum):
    """Errors returned by observability operations."""

    NOT_FOUND = "not_found"
    QUERY_FAILED = "query_failed"
    NOT_IMPLEMENTED = "not_implemented"


class TriggerError(StrEnum):
    """Errors returned by trigger operations."""

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    ALREADY_PAUSED = "already_paused"
    ALREADY_ACTIVE = "already_active"
    ALREADY_DELETED = "already_deleted"
    PRESET_NOT_FOUND = "preset_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"


class OrganizationError(StrEnum):
    """Errors returned by organization operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_DELETED = "already_deleted"
    INVALID_INPUT = "invalid_input"
    HAS_SYSTEMS = "has_systems"
    HAS_REPOS = "has_repos"


class SystemErrorCode(StrEnum):
    """Errors returned by system operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_DELETED = "already_deleted"
    INVALID_INPUT = "invalid_input"
    ORGANIZATION_NOT_FOUND = "organization_not_found"
    HAS_REPOS = "has_repos"


class RepoError(StrEnum):
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
    TRIGGER_CHECK_FAILED = "trigger_check_failed"


class ConfigError(StrEnum):
    """Errors returned by config operations."""

    LOAD_FAILED = "load_failed"


# ---------------------------------------------------------------------------
# Request models — Pydantic schemas for API request bodies
# ---------------------------------------------------------------------------


class CreateOrganizationRequest(BaseModel):
    """Request body for creating a new organization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    slug: str
    created_by: str = "api"


class UpdateOrganizationRequest(BaseModel):
    """Request body for updating an organization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    slug: str | None = None


class RegisterRepoRequest(BaseModel):
    """Request body for registering a new repo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: str = "_unaffiliated"
    full_name: str
    provider: str = "github"
    owner: str = ""
    default_branch: str = "main"
    provider_repo_id: str = ""
    installation_id: str = ""
    is_private: bool = False
    created_by: str = "api"


class UpdateRepoRequest(BaseModel):
    """Request body for updating a repo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_branch: str | None = None
    is_private: bool | None = None
    installation_id: str | None = None
    updated_by: str = "api"


class AssignRepoToSystemRequest(BaseModel):
    """Request body for assigning a repo to a system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_id: str


class CreateSystemRequest(BaseModel):
    """Request body for creating a new system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: str
    name: str
    description: str = ""
    created_by: str = "api"


class UpdateSystemRequest(BaseModel):
    """Request body for updating a system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    description: str | None = None


class TriggerConfigRequest(BaseModel):
    """Safety configuration for a trigger rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = 3
    daily_limit: int = 20
    debounce_seconds: int = 0
    cooldown_seconds: int = 300


class ConditionRequest(BaseModel):
    """A single trigger condition (field operator value)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    operator: str
    value: str


class RegisterTriggerRequest(BaseModel):
    """Request body for registering a new trigger rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    event: str
    repository: str
    workflow_id: str
    conditions: list[ConditionRequest] | None = None
    installation_id: str = ""
    input_mapping: dict[str, str] | None = None
    config: TriggerConfigRequest | None = None
    created_by: str = "api"


class EnablePresetRequest(BaseModel):
    """Request body for enabling a trigger preset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    installation_id: str = ""
    created_by: str = "api"
    workflow_id: str = ""


class UpdateTriggerRequest(BaseModel):
    """Request body for updating (pause/resume) a trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["pause", "resume"]
    reason: str | None = None
    paused_by: str = "api"
    resumed_by: str = "api"


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
    execution_type: str = "sequential"
    max_tokens: int | None = None
    input_artifact_types: list[str] = Field(default_factory=list)
    output_artifact_types: list[str] = Field(default_factory=list)


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
    repository_url: str | None = None
    """Template-level repository URL (single-repo workflows)."""
    repos: list[str] = Field(default_factory=list)
    """Default GitHub URLs for multi-repo workspace hydration (ADR-058)."""


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
    repos: list[str] = Field(default_factory=list)
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""


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
    repos: list[str] = Field(default_factory=list)
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""


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
    workflow_name: str = ""
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
    workflow_name: str = ""
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
    guard_name: str = ""
    block_reason: str = ""


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class ConfigSnapshot(BaseModel):
    """Snapshot of the current application configuration."""

    app: dict = Field(default_factory=dict)
    database: dict = Field(default_factory=dict)
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
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_seconds: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    model: str | None = None
    cost_by_model: dict[str, Decimal] = Field(default_factory=dict)
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
    repos: list[str] = Field(default_factory=list)
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""


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
    cost_by_model: dict[str, Decimal] = Field(default_factory=dict)
    operations: list[ToolOperation] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None


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
    duration_ms: float = 0.0
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
    size_bytes: int | None = None
    execution_id: str | None = None
    workflow_id: str | None = None
    phase_id: str | None = None
    success: bool | None = None


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


# ---------------------------------------------------------------------------
# Shared base response models
# ---------------------------------------------------------------------------


class StatusActionResponse(BaseModel):
    """Generic response for create/update/delete actions."""

    entity_id: str
    status: str


class PaginatedResponse(BaseModel):
    """Base for paginated list responses. Subclass and add typed items field."""

    total: int


# ---------------------------------------------------------------------------
# Repo response models
# ---------------------------------------------------------------------------


class RepoCreatedResponse(BaseModel):
    """Response after registering a new repo."""

    repo_id: str
    full_name: str


class RepoActionResponse(BaseModel):
    """Response for repo mutation actions (update, deregister, assign, unassign)."""

    repo_id: str
    status: str
    system_id: str | None = None


class RepoListResponse(BaseModel):
    """Paginated list of repos."""

    repos: list[RepoSummaryResponse] = Field(default_factory=list)
    total: int = 0


class RepoHealthResponse(BaseModel):
    """Per-repo health snapshot with success rate, trend, and accumulated costs.

    Note: ``recent_cost_usd`` is accumulated from WorkflowCompleted/Failed events
    since the projection was last reset — it is not a fixed time window and may
    differ from ``RepoCostResponse.total_cost_usd`` which is a TimescaleDB total.
    """

    repo_id: str = ""
    repo_full_name: str = ""
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    success_rate: float = 0.0
    trend: str = "stable"
    recent_cost_usd: str = "0"
    window_tokens: int = 0
    last_execution_at: str = ""


class RepoCostResponse(BaseModel):
    """Per-repo cost breakdown by workflow and model."""

    repo_id: str = ""
    repo_full_name: str = ""
    total_cost_usd: str = "0"
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_workflow: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    execution_count: int = 0


class RepoActivityEntryResponse(BaseModel):
    """Single entry in a repo's execution timeline."""

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    trigger_source: str = ""


class RepoActivityResponse(BaseModel):
    """Paginated list of repo activity entries."""

    entries: list[RepoActivityEntryResponse] = Field(default_factory=list)
    total: int = 0


class RepoFailureEntryResponse(BaseModel):
    """A failed execution record for a repository."""

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    failed_at: datetime | None = None
    error_message: str = ""
    error_type: str = ""
    phase_name: str = ""
    conversation_tail: list[str] = Field(default_factory=list)


class RepoFailuresResponse(BaseModel):
    """Paginated list of repo failure entries."""

    failures: list[RepoFailureEntryResponse] = Field(default_factory=list)
    total: int = 0


class RepoSessionEntryResponse(BaseModel):
    """Lightweight session record for repo insight views."""

    id: str
    execution_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    agent_type: str = ""
    total_tokens: int = 0
    total_cost_usd: str = "0"


class RepoSessionsResponse(BaseModel):
    """Paginated list of repo session entries."""

    sessions: list[RepoSessionEntryResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# System response models
# ---------------------------------------------------------------------------


class SystemCreatedResponse(BaseModel):
    """Response after creating a new system."""

    system_id: str
    name: str


class SystemActionResponse(BaseModel):
    """Response for system mutation actions (update, delete)."""

    system_id: str
    status: str


class SystemListResponse(BaseModel):
    """Paginated list of systems."""

    systems: list[SystemSummaryResponse] = Field(default_factory=list)
    total: int = 0


class RepoStatusEntryResponse(BaseModel):
    """Health status for a single repo within a system."""

    repo_id: str = ""
    repo_full_name: str = ""
    status: str = "inactive"
    success_rate: float = 0.0
    active_executions: int = 0
    last_execution_at: str = ""


class SystemStatusResponse(BaseModel):
    """Cross-repo health overview within a system."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    overall_status: str = "healthy"
    total_repos: int = 0
    healthy_repos: int = 0
    degraded_repos: int = 0
    failing_repos: int = 0
    repos: list[RepoStatusEntryResponse] = Field(default_factory=list)


class SystemCostResponse(BaseModel):
    """System-wide cost breakdown by repo, workflow, and model."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    total_cost_usd: str = "0"
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_repo: dict[str, str] = Field(default_factory=dict)
    cost_by_workflow: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    execution_count: int = 0


class SystemActivityResponse(BaseModel):
    """Paginated list of system activity entries."""

    entries: list[RepoActivityEntryResponse] = Field(default_factory=list)
    total: int = 0


class FailurePatternResponse(BaseModel):
    """A recurring failure pattern within a system."""

    error_type: str = ""
    error_message: str = ""
    occurrence_count: int = 0
    affected_repos: list[str] = Field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""


class CostOutlierResponse(BaseModel):
    """An execution with unusually high cost."""

    execution_id: str = ""
    repo_full_name: str = ""
    workflow_name: str = ""
    cost_usd: str = "0"
    median_cost_usd: str = "0"
    deviation_factor: float = 0.0
    executed_at: str = ""


class SystemPatternsResponse(BaseModel):
    """Recurring failure and cost patterns within a system."""

    system_id: str = ""
    system_name: str = ""
    failure_patterns: list[FailurePatternResponse] = Field(default_factory=list)
    cost_outliers: list[CostOutlierResponse] = Field(default_factory=list)
    analysis_window_hours: int = 168


class SystemHistoryResponse(BaseModel):
    """Paginated list of system history entries."""

    entries: list[RepoActivityEntryResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Trigger response models
# ---------------------------------------------------------------------------


class TriggerActionResponse(BaseModel):
    """Response for trigger create/update/delete actions."""

    trigger_id: str
    name: str | None = None
    status: str
    preset: str | None = None
    action: str | None = None


class TriggerListResponse(PaginatedResponse):
    """Paginated list of trigger summaries."""

    triggers: list[TriggerSummary] = Field(default_factory=list)


class TriggerHistoryListEntry(BaseModel):
    """Entry in a cross-trigger history listing."""

    trigger_id: str
    fired_at: str | None = None
    execution_id: str = ""
    event_type: str = ""
    pr_number: int | None = None
    status: str = "dispatched"
    guard_name: str = ""
    block_reason: str = ""


class TriggerHistoryListResponse(PaginatedResponse):
    """Paginated list of trigger history entries (global)."""

    entries: list[TriggerHistoryListEntry] = Field(default_factory=list)


class TriggerHistoryEntryResponse(BaseModel):
    """Single entry in a trigger-specific history response."""

    fired_at: str | None = None
    execution_id: str = ""
    webhook_delivery_id: str = ""
    event_type: str = ""
    pr_number: int | None = None
    status: str = "dispatched"
    cost_usd: float | None = None
    guard_name: str = ""
    block_reason: str = ""


class TriggerHistoryResponse(BaseModel):
    """History entries for a specific trigger."""

    trigger_id: str
    entries: list[TriggerHistoryEntryResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Organization response models
# ---------------------------------------------------------------------------


class OrganizationActionResponse(BaseModel):
    """Response for organization create/update/delete actions."""

    organization_id: str
    name: str | None = None
    slug: str | None = None
    status: str


class OrganizationListResponse(PaginatedResponse):
    """Paginated list of organizations."""

    organizations: list[OrganizationSummaryResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Insight response models
# ---------------------------------------------------------------------------


class SystemOverviewEntryResponse(BaseModel):
    """Summary of a single system for global overview."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    organization_name: str = ""
    repo_count: int = 0
    overall_status: str = "healthy"
    active_executions: int = 0
    total_cost_usd: str = "0"


class GlobalOverviewResponse(BaseModel):
    """Global overview of all systems and repos."""

    total_systems: int = 0
    total_repos: int = 0
    unassigned_repos: int = 0
    total_active_executions: int = 0
    total_cost_usd: str = "0"
    systems: list[SystemOverviewEntryResponse] = Field(default_factory=list)


class GlobalCostResponse(BaseModel):
    """Global cost breakdown across all repos."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    total_cost_usd: str = "0"
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_repo: dict[str, str] = Field(default_factory=dict)
    cost_by_workflow: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    execution_count: int = 0


class HeatmapDayBucketResponse(BaseModel):
    """Single day's aggregated activity."""

    date: str
    count: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)


class ContributionHeatmapResponse(BaseModel):
    """Contribution heatmap data."""

    metric: str
    start_date: str
    end_date: str
    total: float = 0.0
    days: list[HeatmapDayBucketResponse] = Field(default_factory=list)
    filter: dict[str, str | None] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Observability response models
# ---------------------------------------------------------------------------


class ToolTimelineEntry(BaseModel):
    """Single entry in a tool execution timeline."""

    observation_id: str = ""
    operation_type: str = ""
    tool_name: str | None = None
    timestamp: datetime | None = None
    duration_ms: float | None = None
    success: bool | None = None


class ToolTimelineResponse(BaseModel):
    """Tool execution timeline for a session."""

    session_id: str
    total_executions: int = 0
    executions: list[ToolTimelineEntry] = Field(default_factory=list)


class SessionTokenMetrics(BaseModel):
    """Token usage metrics for a session."""

    session_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: str = "0"
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


# ---------------------------------------------------------------------------
# Artifact action response models
# ---------------------------------------------------------------------------


class ArtifactActionResponse(BaseModel):
    """Response for artifact update/delete actions."""

    artifact_id: str
    status: str


# ---------------------------------------------------------------------------
# SSE health response model
# ---------------------------------------------------------------------------


class SSEHealthResponse(BaseModel):
    """Health status of the SSE subsystem."""

    status: str
    active_executions: int | None = None
    active_connections: int | None = None
