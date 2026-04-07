"""Trigger configuration value object.

Safety and operational configuration for a trigger rule.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerConfig:
    """Safety configuration for a trigger rule.

    Attributes:
        max_attempts: Max fires per (PR, trigger) combination.
        daily_limit: Max triggers per day for this rule.
        debounce_seconds: Wait before evaluating (batch rapid events).
        cooldown_seconds: Min time between fires for same PR.
    """

    max_attempts: int = 3
    daily_limit: int = 20
    debounce_seconds: int = 0
    cooldown_seconds: int = 300

    def __post_init__(self) -> None:
        """Validate the configuration."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.daily_limit < 1:
            raise ValueError("daily_limit must be >= 1")
        if self.debounce_seconds < 0:
            raise ValueError("debounce_seconds must be >= 0")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
