"""Typed response models and helpers for workflow API responses."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from syn_cli._output import console


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


_TYPE_COERCIONS: list[tuple[re.Pattern[str], type]] = [
    (re.compile(r"^-?\d+$"), int),
    (re.compile(r"^-?\d+\.\d+$"), float),
]


def _is_quoted(value: str) -> bool:
    """Check if value is wrapped in matching quotes."""
    return len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'")


def _parse_single_value(value: str) -> str | int | float | bool:
    """Parse a single input value with type coercion."""
    if _is_quoted(value):
        return value[1:-1]
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return _coerce_value(value)


def parse_inputs(inputs: list[str] | None) -> dict[str, Any]:
    """Parse key=value input pairs into a typed dictionary."""
    if not inputs:
        return {}

    result: dict[str, Any] = {}
    for item in inputs:
        if "=" not in item:
            console.print(
                f"[yellow]Warning: Ignoring invalid input '{item}' (expected key=value)[/yellow]"
            )
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = _parse_single_value(value)

    return result


def _coerce_value(value: str) -> str | int | float:
    """Try numeric coercion, fall back to string."""
    for pattern, converter in _TYPE_COERCIONS:
        if pattern.match(value):
            return converter(value)
    return value
