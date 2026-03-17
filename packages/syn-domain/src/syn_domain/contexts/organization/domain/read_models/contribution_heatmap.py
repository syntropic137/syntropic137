"""Contribution heatmap read models.

Daily bucketed activity data for GitHub-style contribution heatmaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HeatmapDayBucket:
    """Single day's aggregated activity.

    Attributes:
        date: ISO date string (YYYY-MM-DD).
        count: Value of the selected metric for this day.
        breakdown: Full breakdown of all metrics for this day.
    """

    date: str
    count: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeatmapDayBucket:
        """Create from dictionary data."""
        return cls(
            date=data.get("date", ""),
            count=data.get("count", 0.0),
            breakdown=dict(data.get("breakdown", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "date": self.date,
            "count": self.count,
            "breakdown": dict(self.breakdown),
        }


@dataclass(frozen=True)
class ContributionHeatmapResult:
    """Complete heatmap result with metadata.

    Attributes:
        metric: The primary metric used for intensity values.
        start_date: Start of the date range.
        end_date: End of the date range.
        total: Sum of count across all days.
        days: List of daily buckets.
        filter: Applied filters (org/system/repo).
    """

    metric: str
    start_date: str
    end_date: str
    total: float = 0.0
    days: list[HeatmapDayBucket] = field(default_factory=list)
    filter: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContributionHeatmapResult:
        """Create from dictionary data."""
        return cls(
            metric=data.get("metric", "sessions"),
            start_date=data.get("start_date", ""),
            end_date=data.get("end_date", ""),
            total=data.get("total", 0.0),
            days=[HeatmapDayBucket.from_dict(d) for d in data.get("days", [])],
            filter=dict(data.get("filter", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "metric": self.metric,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total": self.total,
            "days": [d.to_dict() for d in self.days],
            "filter": dict(self.filter),
        }
