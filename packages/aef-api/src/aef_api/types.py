"""Result type and shared Pydantic models for the AEF API.

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
    INVALID_INPUT = "invalid_input"
    EXECUTION_FAILED = "execution_failed"
    NOT_IMPLEMENTED = "not_implemented"


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


class GitHubError(str, Enum):
    """Errors returned by GitHub operations."""

    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
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


class WorkflowDetail(BaseModel):
    """Detailed workflow template response."""

    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinitionResponse] = Field(default_factory=list)
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
