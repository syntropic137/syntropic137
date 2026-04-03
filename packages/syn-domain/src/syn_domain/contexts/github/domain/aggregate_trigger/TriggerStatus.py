"""Trigger rule status enum."""

from enum import StrEnum


class TriggerStatus(StrEnum):
    """Status of a trigger rule."""

    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"
