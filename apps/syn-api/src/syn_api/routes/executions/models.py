"""Pydantic response models for execution query endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from syn_shared.display import EM_DASH


class PhaseOperationInfo(BaseModel):
    operation_id: str
    operation_type: str
    timestamp: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    success: bool = True


class PhaseExecutionInfo(BaseModel):
    phase_id: str
    name: str
    status: str
    session_id: str | None = None
    artifact_id: str | None = None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    duration_seconds: float = 0.0
    cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    provider: str | None = None
    """Harness the phase ran on, e.g. ``claude`` / ``codex`` (issue #1094).

    Paired with ``model`` this is the ``claude/opus`` label an operator needs
    to see that a heterogeneous run drifted onto the wrong harness or model.
    """
    model: str | None = None
    model_display: str | None = None
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    operations: list[PhaseOperationInfo] = Field(default_factory=list)


class ExecutionDetailResponse(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    phases: list[PhaseExecutionInfo] = Field(default_factory=list)
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_tokens: int
    total_cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    total_duration_seconds: float = 0.0
    artifact_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None
    repos: list[str] = Field(default_factory=list)


class ExecutionSummaryResponse(BaseModel):
    """Summary of a workflow execution.

    Display fields (``*_display``) are produced server-side so all clients
    (dashboard, CLI, future UIs) share identical human-readable output. Raw
    fields remain for programmatic consumers; both are always present.

    See: docs/adrs/ADR-064-observability-monitor-ui.md
    """

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int
    total_tokens_display: str = "0"
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_cost_usd: Decimal = Decimal("0")
    total_cost_display: str = EM_DASH
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    duration_seconds: float | None = None
    duration_display: str = "—"
    tool_call_count: int = 0
    error_message: str | None = None
    repos: list[str] = Field(default_factory=list)
    repos_display: str | None = None
    models: list[str] = Field(default_factory=list)
    """Distinct models that ran, sorted (issue #1094).

    The list is the screen an operator scans, and until this field existed it
    could not say what ran: a workflow meant for opus spent a long time on
    sonnet and nothing on this row disagreed.
    """
    models_display: str | None = None


class ExecutionListResponse(BaseModel):
    executions: list[ExecutionSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 50
