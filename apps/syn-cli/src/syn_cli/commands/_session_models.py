"""Typed response models for session API responses."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionSummaryResponse(BaseModel):
    """Summary of a session from the list endpoint."""

    model_config = ConfigDict(extra="ignore")

    id: str
    workflow_id: str | None = None
    execution_id: str | None = None
    status: str = "unknown"
    agent_provider: str | None = None
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    started_at: str | None = None
    completed_at: str | None = None


class OperationInfo(BaseModel):
    """Single operation within a session."""

    model_config = ConfigDict(extra="ignore")

    operation_id: str = ""
    operation_type: str = ""
    timestamp: str | None = None
    duration_seconds: float | None = None
    success: bool = True
    tool_name: str | None = None
    total_tokens: int | None = None


class SessionDetailResponse(BaseModel):
    """Full detail of a session."""

    model_config = ConfigDict(extra="ignore")

    id: str
    workflow_id: str | None = None
    workflow_name: str | None = None
    execution_id: str | None = None
    agent_provider: str | None = None
    agent_model: str | None = None
    status: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    operations: list[OperationInfo] = []
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = {}
