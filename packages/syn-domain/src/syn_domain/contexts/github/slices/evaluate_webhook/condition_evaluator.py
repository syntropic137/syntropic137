"""Condition evaluator for trigger rules.

Evaluates trigger conditions against GitHub webhook payloads.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
        TriggerCondition,
    )

# Type alias for condition values (matches TriggerCondition.value)
ConditionValue = str | int | bool | list[str] | None


def _coerce_bool(value: object) -> object:
    """Coerce string-encoded booleans to native Python bools.

    Conditions may arrive with string values from CLI or raw API calls
    (e.g. ``"false"`` instead of ``False``).
    """
    if not isinstance(value, str):
        return value
    lower = value.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    return value


def _coerce_to_list(value: object) -> list[object]:
    """Coerce a value to a list for membership operators (in/not_in).

    Handles comma-separated strings from CLI (``"a,b"`` → ``["a", "b"]``),
    passes through existing lists, and wraps scalars.
    """
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str) and "," in value:
        return [v.strip() for v in value.split(",")]
    return [value]


def _check_operator(operator: str, resolved: object, value: object) -> bool:
    """Evaluate a single operator against resolved and expected values.

    Returns True if the condition passes, False if it fails.
    """
    match operator:
        case "eq":
            return resolved == _coerce_bool(value)
        case "neq":
            return resolved != _coerce_bool(value)
        case "not_empty":
            return bool(resolved)
        case "is_empty":
            return not resolved
        case "in":
            return resolved in _coerce_to_list(value)
        case "not_in":
            return resolved not in _coerce_to_list(value)
        case "contains":
            return value in (resolved or "")  # type: ignore[operator]  # resolved is object
        case _:
            raise ValueError(f"Unknown operator: {operator}")


def _unpack_condition(condition: TriggerCondition | dict[str, object]) -> tuple[str, str, object]:
    """Extract (field, operator, value) from a typed or dict condition."""
    if isinstance(condition, dict):
        return (
            str(condition.get("field", "")),
            str(condition.get("operator", "eq")),
            condition.get("value"),
        )
    return condition.field, condition.operator, condition.value


def evaluate_conditions(
    conditions: Sequence[TriggerCondition | dict[str, object]],
    payload: dict[str, object],
) -> bool:
    for condition in conditions:
        field, operator, value = _unpack_condition(condition)
        resolved = _resolve_field(payload, field)
        if not _check_operator(operator, resolved, value):
            return False
    return True


# Regex to match array index access like "pull_requests[0]"
_ARRAY_INDEX_RE = re.compile(r"^(.+)\[(\d+)\]$")


def _resolve_array_index(current: object, key: str, index_str: str) -> object:
    """Resolve an array-indexed access like ``items[0]`` on *current*."""
    if not isinstance(current, dict):
        return None
    current = current.get(key)
    if not isinstance(current, (list, tuple)):
        return None
    idx = int(index_str)
    return current[idx] if idx < len(current) else None


def _resolve_one_part(current: object, part: str) -> object:
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


def _resolve_field(payload: dict[str, object], field_path: str) -> object:
    """Resolve a dot-notation field path from a payload dict.

    Supports array indexing: "check_run.pull_requests[0].number"
    """
    current: object = payload
    for part in field_path.split("."):
        current = _resolve_one_part(current, part)
    return current


def extract_inputs(
    payload: dict[str, object],
    input_mapping: dict[str, str],
) -> dict[str, object]:
    """Extract workflow inputs from a payload using input_mapping.

    Args:
        payload: The webhook payload.
        input_mapping: Map of workflow input names to payload field paths.

    Returns:
        Dict of extracted input values.
    """
    inputs: dict[str, object] = {}
    for input_name, field_path in input_mapping.items():
        value = _resolve_field(payload, field_path)
        if value is not None:
            inputs[input_name] = value
    return inputs
