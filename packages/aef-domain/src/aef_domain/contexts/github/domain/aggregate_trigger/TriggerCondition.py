"""Trigger condition value object.

Represents a single condition that must be met for a trigger to fire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ALLOWED_OPERATORS = ("eq", "neq", "in", "not_in", "not_empty", "is_empty", "contains")


@dataclass(frozen=True)
class TriggerCondition:
    """A condition evaluated against the GitHub webhook payload.

    Uses dot-notation paths to traverse nested payloads.

    Examples:
        TriggerCondition("check_run.conclusion", "eq", "failure")
        TriggerCondition("check_run.pull_requests", "not_empty", None)
        TriggerCondition("review.state", "eq", "changes_requested")

    Attributes:
        field: Dot-notation path into the webhook payload.
        operator: Comparison operator (eq|neq|in|not_in|not_empty|is_empty|contains).
        value: Expected value (None for unary operators like not_empty/is_empty).
    """

    field: str
    operator: str
    value: Any = None

    def __post_init__(self) -> None:
        """Validate the condition."""
        if not self.field:
            raise ValueError("field is required")
        if self.operator not in ALLOWED_OPERATORS:
            raise ValueError(f"operator must be one of {ALLOWED_OPERATORS}, got '{self.operator}'")
