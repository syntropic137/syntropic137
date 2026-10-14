"""Throwaway probe for proving mutation-evidence.yml. Never merged."""

from __future__ import annotations


def clamp(value: int, low: int, high: int) -> int:
    """Clamp `value` into [low, high]."""
    if value < low:
        return low

    if value > high:
        return high
    return value
