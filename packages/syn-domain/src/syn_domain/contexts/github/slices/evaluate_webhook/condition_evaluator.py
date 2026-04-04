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


def _coerce_value(value: Any) -> Any:
    """Coerce string-encoded values to their native Python types.

    Conditions may arrive with string values from CLI or raw API calls
    (e.g. ``"false"`` instead of ``False``, ``"a,b"`` instead of ``["a","b"]``).
    This ensures consistent evaluation regardless of how the trigger was registered.
    """
    if not isinstance(value, str):
        return value
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    # Comma-separated strings → list (for "in" / "not_in" operators)
    if "," in value:
        return [v.strip() for v in value.split(",")]
    return value


def _check_operator(operator: str, resolved: Any, value: Any) -> bool:
    """Evaluate a single operator against resolved and expected values.

    Returns True if the condition passes, False if it fails.
    """
    value = _coerce_value(value)
    match operator:
        case "eq":
            return resolved == value
        case "neq":
            return resolved != value
        case "not_empty":
            return bool(resolved)
        case "is_empty":
            return not resolved
        case "in":
            return resolved in (value if isinstance(value, list) else (value or []))
        case "not_in":
            return resolved not in (value if isinstance(value, list) else (value or []))
        case "contains":
            return value in (resolved or "")  # type: ignore[operator]  # resolved is Any
        case _:
            raise ValueError(f"Unknown operator: {operator}")


def _unpack_condition(condition: TriggerCondition | dict) -> tuple[str, str, Any]:
    """Extract (field, operator, value) from a typed or dict condition."""
    if isinstance(condition, dict):
        return condition.get("field", ""), condition.get("operator", "eq"), condition.get("value")
    return condition.field, condition.operator, condition.value


def evaluate_conditions(
    conditions: list[TriggerCondition | dict],
    payload: dict[str, Any],
) -> bool:
    for condition in conditions:
        field, operator, value = _unpack_condition(condition)
        resolved = _resolve_field(payload, field)
        if not _check_operator(operator, resolved, value):
            return False
    return True


# Regex to match array index access like "pull_requests[0]"
_ARRAY_INDEX_RE = re.compile(r"^(.+)\[(\d+)\]$")


def _resolve_array_index(current: Any, key: str, index_str: str) -> Any:
    """Resolve an array-indexed access like ``items[0]`` on *current*."""
    if not isinstance(current, dict):
        return None
    current = current.get(key)
    if not isinstance(current, (list, tuple)):
        return None
    idx = int(index_str)
    return current[idx] if idx < len(current) else None


def _resolve_one_part(current: Any, part: str) -> Any:
    """Resolve a single path segment (plain key or array-indexed) from *current*."""
    if current is None:
        return None
    match = _ARRAY_INDEX_RE.match(part)
    if match:
        key, index_str = match.groups()
        return _resolve_array_index(current, key, index_str)
    if isinstance(current, dict):
        return current.get(part)
    return None


def _resolve_field(payload: dict, field_path: str) -> Any:
    """Resolve a dot-notation field path from a payload dict.

    Supports array indexing: "check_run.pull_requests[0].number"
    """
    current: Any = payload
    for part in field_path.split("."):
        current = _resolve_one_part(current, part)
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
