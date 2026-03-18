"""Typed response models for cost API responses."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SessionCostResponse(BaseModel):
    """Cost data for a single session."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    execution_id: str | None = None
    total_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    duration_ms: float = 0.0
    cost_by_model: dict[str, str] = {}
    cost_by_tool: dict[str, str] = {}
    is_finalized: bool = False
    started_at: str | None = None
    completed_at: str | None = None


class ExecutionCostResponse(BaseModel):
    """Cost data for a workflow execution."""

    model_config = ConfigDict(extra="ignore")

    execution_id: str
    workflow_id: str | None = None
    session_count: int = 0
    total_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    duration_ms: float = 0.0
    cost_by_phase: dict[str, str] = {}
    cost_by_model: dict[str, str] = {}
    cost_by_tool: dict[str, str] = {}
    is_complete: bool = False
    started_at: str | None = None
    completed_at: str | None = None


class CostSummaryResponse(BaseModel):
    """Aggregated cost summary."""

    model_config = ConfigDict(extra="ignore")

    total_cost_usd: Decimal = Decimal("0")
    total_sessions: int = 0
    total_executions: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    top_models: list[dict[str, str]] = []
    top_sessions: list[dict[str, str]] = []
