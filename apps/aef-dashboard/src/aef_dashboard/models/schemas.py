"""Pydantic schemas for API responses."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# WORKFLOW SCHEMAS
# =============================================================================


class WorkflowSummary(BaseModel):
    """Summary of a workflow TEMPLATE for list views.

    Note: Templates don't have status. Status belongs to executions.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    workflow_type: str
    phase_count: int
    created_at: datetime | None = None
    runs_count: int = 0
    """Number of times this workflow has been executed."""


class PhaseDefinition(BaseModel):
    """Phase definition within a workflow template.

    This is the template definition, not execution state.
    For phase execution details, see PhaseExecutionDetail.
    """

    phase_id: str
    name: str
    order: int = 0
    description: str | None = None
    agent_type: str = ""


class WorkflowResponse(BaseModel):
    """Detailed workflow TEMPLATE response.

    Templates don't have execution status.
    For execution details, use /api/executions/{id}.
    """

    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinition] = Field(default_factory=list)
    created_at: datetime | None = None
    runs_count: int = 0
    """Number of times this workflow has been executed."""
    runs_link: str | None = None
    """Link to execution runs: /api/workflows/{id}/runs"""


class WorkflowListResponse(BaseModel):
    """Response for workflow list endpoint."""

    workflows: list[WorkflowSummary]
    total: int
    page: int = 1
    page_size: int = 20


# =============================================================================
# SESSION SCHEMAS
# =============================================================================


class SessionSummary(BaseModel):
    """Summary of an agent session."""

    id: str
    workflow_id: str | None
    execution_id: str | None = None
    phase_id: str | None
    status: str
    agent_provider: str | None
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    started_at: datetime | None = None
    completed_at: datetime | None = None


class OperationInfo(BaseModel):
    """Information about a session operation.

    Supports multiple operation types for full observability:
    - MESSAGE_REQUEST/RESPONSE: LLM API calls
    - TOOL_STARTED/COMPLETED/BLOCKED: Tool lifecycle
    - THINKING: Extended thinking content
    - ERROR: Error information
    """

    operation_id: str
    operation_type: str
    timestamp: datetime | None = None
    duration_seconds: float | None = None
    success: bool = True

    # Token metrics (for MESSAGE_* types)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Tool details (for TOOL_* types)
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None

    # Message details (for MESSAGE_* types)
    message_role: str | None = None
    message_content: str | None = None

    # Thinking details (for THINKING type)
    thinking_content: str | None = None


class SessionResponse(BaseModel):
    """Detailed session response."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    milestone_id: str | None
    agent_provider: str | None
    agent_model: str | None
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    operations: list[OperationInfo] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# ARTIFACT SCHEMAS
# =============================================================================


class ArtifactSummary(BaseModel):
    """Summary of an artifact."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    artifact_type: str
    title: str | None = None
    size_bytes: int = 0
    created_at: datetime | None = None


class ArtifactResponse(BaseModel):
    """Detailed artifact response."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    session_id: str | None
    artifact_type: str
    is_primary_deliverable: bool = True
    content: str | None = None
    content_type: str = "text/markdown"
    content_hash: str | None = None
    size_bytes: int = 0
    title: str | None = None
    derived_from: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# METRICS SCHEMAS
# =============================================================================


class PhaseMetrics(BaseModel):
    """Metrics for a single phase."""

    phase_id: str
    phase_name: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_seconds: float = 0.0
    artifact_count: int = 0


class MetricsResponse(BaseModel):
    """Aggregated metrics response."""

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
    phases: list[PhaseMetrics] = Field(default_factory=list)


# =============================================================================
# EXECUTION HISTORY SCHEMAS
# =============================================================================


class ExecutionRunSummary(BaseModel):
    """Summary of a single execution run for list views."""

    execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    error_message: str | None = None


class ExecutionRunListResponse(BaseModel):
    """Response for listing workflow execution runs."""

    runs: list[ExecutionRunSummary]
    total: int
    workflow_id: str
    workflow_name: str


class ExecutionRun(BaseModel):
    """A single execution run of a workflow (detailed view)."""

    execution_id: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    phase_results: list[PhaseMetrics] = Field(default_factory=list)
    error_message: str | None = None


class ExecutionHistoryResponse(BaseModel):
    """Response for workflow execution history."""

    workflow_id: str
    workflow_name: str
    executions: list[ExecutionRun] = Field(default_factory=list)
    total_executions: int = 0


# =============================================================================
# EVENT SCHEMAS (for SSE)
# =============================================================================


class EventMessage(BaseModel):
    """Event message for SSE stream."""

    event_type: str
    timestamp: datetime
    workflow_id: str | None = None
    phase_id: str | None = None
    session_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# EXECUTION SCHEMAS
# =============================================================================


class ExecuteWorkflowRequest(BaseModel):
    """Request to execute a workflow."""

    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Input variables for the workflow (e.g., topic, context)",
    )
    provider: str = Field(
        default="claude",
        description="Agent provider to use (claude, openai, mock)",
    )
    max_budget_usd: float | None = Field(
        default=None,
        description="Maximum budget in USD for this execution",
    )


class ExecuteWorkflowResponse(BaseModel):
    """Response after starting workflow execution."""

    execution_id: str
    workflow_id: str
    status: str = "started"
    message: str = "Workflow execution started"


class ExecutionStatusResponse(BaseModel):
    """Response for execution status check."""

    execution_id: str
    workflow_id: str
    status: str
    current_phase: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
