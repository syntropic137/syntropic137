"""Typed response models for workflow API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class WorkflowSummary(BaseModel):
    """Summary of a workflow from the list endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    workflow_type: str
    phase_count: int = 0


class WorkflowDetail(BaseModel):
    """Detail of a workflow from the show endpoint."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    workflow_type: str
    classification: str = ""
    phases: list[dict[str, Any]] = []


class ExecutionRunResponse(BaseModel):
    """Response from workflow execution endpoint."""

    model_config = ConfigDict(extra="ignore")

    status: str = "unknown"
    execution_id: str = "unknown"
