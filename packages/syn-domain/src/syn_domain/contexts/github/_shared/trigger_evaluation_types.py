"""Value objects for trigger evaluation results — shared across slices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TriggerMatchResult:
    trigger_id: str
    execution_id: str


@dataclass
class TriggerDeferredResult:
    trigger_id: str
    reason: str
    defer_seconds: float


@dataclass
class TriggerBlockedResult:
    """Result when a trigger evaluation is blocked by a guard or conditions."""

    trigger_id: str
    guard_name: str
    reason: str
