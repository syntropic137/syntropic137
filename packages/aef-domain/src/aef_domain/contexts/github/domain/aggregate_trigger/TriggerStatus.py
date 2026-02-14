"""Trigger rule status enum."""

from enum import Enum


class TriggerStatus(str, Enum):
    """Status of a trigger rule."""

    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"
