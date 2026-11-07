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


EVENTS_API_ACTOR_KEY = "_events_api_actor"
"""Payload key under which the Events API mapper keeps the event's ``actor``.

A polled event has no ``sender``; GitHub names who caused it as the top-level
``actor`` instead. The mapper keeps it under this key, not as ``sender``, so
per-trigger ``sender.*`` conditions see polled payloads exactly as before and
only the contributor guard reads it (#580).
"""
