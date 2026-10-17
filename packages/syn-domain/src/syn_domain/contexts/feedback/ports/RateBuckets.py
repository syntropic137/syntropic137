"""RateBuckets: token buckets Intake spends before doing any expensive work (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from typing import Protocol


class RateBuckets(Protocol):
    async def take(self, bucket: str, *, capacity: int, refill_per_second: float) -> bool:
        """Spend one token. False when the bucket is empty."""
        ...
