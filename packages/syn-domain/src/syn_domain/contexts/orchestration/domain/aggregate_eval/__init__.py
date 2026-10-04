"""Eval aggregate (evals plan, #967): an experiment's goal and pinned baseline."""

from __future__ import annotations

from .errors import (
    DuplicateBaselineRepositoryError,
    EvalAlreadyExistsError,
    EvalArchivedError,
    EvalFrozenError,
    EvalNotCreatedError,
    EvalRuleError,
)
from .EvalAggregate import EvalAggregate
from .value_objects import MAX_GOAL_LENGTH, EvalId, EvalName, Goal

__all__ = [
    "MAX_GOAL_LENGTH",
    "DuplicateBaselineRepositoryError",
    "EvalAggregate",
    "EvalAlreadyExistsError",
    "EvalArchivedError",
    "EvalFrozenError",
    "EvalId",
    "EvalName",
    "EvalNotCreatedError",
    "EvalRuleError",
    "Goal",
]
