"""Condition evaluator for trigger rules.

Evaluates trigger conditions against GitHub webhook payloads.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
        TriggerCondition,
    )


def evaluate_conditions(
    conditions: list[TriggerCondition | dict],
    payload: dict[str, Any],
) -> bool:
    for condition in conditions:
        if isinstance(condition, dict):
            field = condition.get("field", "")
            operator = condition.get("operator", "eq")
            value = condition.get("value")
        else:
            field = condition.field
            operator = condition.operator
            value = condition.value

        resolved = _resolve_field(payload, field)
        match operator:
            case "eq":
                if resolved != value:
                    return False
            case "neq":
                if resolved == value:
                    return False
            case "not_empty":
                if not resolved:
                    return False
            case "is_empty":
                if resolved:
                    return False
            case "in":
                if resolved not in (value or []):
                    return False
            case "not_in":
                if resolved in (value or []):
                    return False
            case "contains":
                if value not in (resolved or ""):  # type: ignore[operator]  # resolved is Any from payload dict traversal
                    return False
            case _:
                raise ValueError(f"Unknown operator: {operator}")
    return True


# Regex to match array index access like "pull_requests[0]"
_ARRAY_INDEX_RE = re.compile(r"^(.+)\[(\d+)\]$")


def _resolve_field(payload: dict, field_path: str) -> Any:
    """Resolve a dot-notation field path from a payload dict.

    Supports array indexing: "check_run.pull_requests[0].number"
    """
    parts = field_path.split(".")
    current: Any = payload
    for part in parts:
        if current is None:
            return None

        # Check for array index access
        match = _ARRAY_INDEX_RE.match(part)
        if match:
            key, index_str = match.groups()
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
            if isinstance(current, (list, tuple)):
                idx = int(index_str)
                if idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def extract_inputs(
    payload: dict[str, Any],
    input_mapping: dict[str, str],
) -> dict[str, Any]:
    """Extract workflow inputs from a payload using input_mapping.

    Args:
        payload: The webhook payload.
        input_mapping: Map of workflow input names to payload field paths.

    Returns:
        Dict of extracted input values.
    """
    inputs: dict[str, Any] = {}
    for input_name, field_path in input_mapping.items():
        value = _resolve_field(payload, field_path)
        if value is not None:
            inputs[input_name] = value
    return inputs
