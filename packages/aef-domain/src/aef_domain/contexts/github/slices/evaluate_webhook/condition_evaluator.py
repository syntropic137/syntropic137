"""Condition evaluator for trigger rules.

Evaluates trigger conditions against GitHub webhook payloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
        TriggerCondition,
    )


def evaluate_conditions(
    conditions: list[TriggerCondition],
    payload: dict[str, Any],
) -> bool:
    """Evaluate all conditions against a webhook payload.

    All conditions must be true (AND logic).
    Uses dot-notation to traverse nested payload.

    Args:
        conditions: List of conditions to evaluate.
        payload: The webhook payload dict.

    Returns:
        True if all conditions pass, False otherwise.
    """
    for condition in conditions:
        value = _resolve_field(payload, condition.field)

        match condition.operator:
            case "eq":
                if value != condition.value:
                    return False
            case "neq":
                if value == condition.value:
                    return False
            case "not_empty":
                if not value:
                    return False
            case "is_empty":
                if value:
                    return False
            case "in":
                if value not in (condition.value or []):
                    return False
            case "not_in":
                if value in (condition.value or []):
                    return False
            case "contains":
                if condition.value not in (value or ""):
                    return False
            case _:
                raise ValueError(f"Unknown operator: {condition.operator}")

    return True


def _resolve_field(payload: dict, field_path: str) -> Any:
    """Resolve a dot-notation field path against a payload.

    Example: "check_run.conclusion" -> payload["check_run"]["conclusion"]

    Args:
        payload: The nested dict to traverse.
        field_path: Dot-notation path.

    Returns:
        The resolved value, or None if path not found.
    """
    parts = field_path.split(".")
    current: Any = payload
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
