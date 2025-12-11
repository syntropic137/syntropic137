"""Statistical analysis for benchmark timings."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TimingStats:
    """Statistical summary of timing measurements."""

    count: int
    min_ms: float
    max_ms: float
    mean_ms: float
    median_ms: float
    std_dev_ms: float
    p50_ms: float
    p75_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float

    @classmethod
    def from_timings(cls, timings_ms: list[float]) -> TimingStats:
        """Calculate statistics from a list of timings.

        Args:
            timings_ms: List of timing values in milliseconds

        Returns:
            TimingStats with calculated statistics
        """
        if not timings_ms:
            return cls(
                count=0,
                min_ms=0,
                max_ms=0,
                mean_ms=0,
                median_ms=0,
                std_dev_ms=0,
                p50_ms=0,
                p75_ms=0,
                p90_ms=0,
                p95_ms=0,
                p99_ms=0,
            )

        sorted_timings = sorted(timings_ms)
        n = len(sorted_timings)

        # Basic stats
        min_val = sorted_timings[0]
        max_val = sorted_timings[-1]
        mean_val = sum(sorted_timings) / n

        # Standard deviation
        if n > 1:
            variance = sum((x - mean_val) ** 2 for x in sorted_timings) / (n - 1)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0

        # Percentiles
        def percentile(p: float) -> float:
            """Calculate percentile value."""
            if n == 1:
                return sorted_timings[0]
            k = (n - 1) * p
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return sorted_timings[int(k)]
            return sorted_timings[int(f)] * (c - k) + sorted_timings[int(c)] * (k - f)

        return cls(
            count=n,
            min_ms=min_val,
            max_ms=max_val,
            mean_ms=mean_val,
            median_ms=percentile(0.5),
            std_dev_ms=std_dev,
            p50_ms=percentile(0.5),
            p75_ms=percentile(0.75),
            p90_ms=percentile(0.90),
            p95_ms=percentile(0.95),
            p99_ms=percentile(0.99),
        )

    @property
    def min_seconds(self) -> float:
        """Minimum in seconds."""
        return self.min_ms / 1000

    @property
    def max_seconds(self) -> float:
        """Maximum in seconds."""
        return self.max_ms / 1000

    @property
    def mean_seconds(self) -> float:
        """Mean in seconds."""
        return self.mean_ms / 1000

    @property
    def p95_seconds(self) -> float:
        """P95 in seconds."""
        return self.p95_ms / 1000

    @property
    def p99_seconds(self) -> float:
        """P99 in seconds."""
        return self.p99_ms / 1000

    def format_ms(self, value_ms: float) -> str:
        """Format milliseconds for display."""
        if value_ms < 1000:
            return f"{value_ms:.0f}ms"
        return f"{value_ms / 1000:.2f}s"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "count": self.count,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "median_ms": self.median_ms,
            "std_dev_ms": self.std_dev_ms,
            "p50_ms": self.p50_ms,
            "p75_ms": self.p75_ms,
            "p90_ms": self.p90_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
        }
