"""Pydantic response models for execution query endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


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
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    cost_usd: Decimal = Decimal("0")
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    model: str | None = None
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
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_duration_seconds: float = 0.0
    artifact_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


class ExecutionSummaryResponse(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    tool_call_count: int = 0
    error_message: str | None = None


class ExecutionListResponse(BaseModel):
    executions: list[ExecutionSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 50
