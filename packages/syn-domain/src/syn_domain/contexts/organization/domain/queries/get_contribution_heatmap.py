"""Get Contribution Heatmap query.

Query to retrieve daily activity buckets for a contribution heatmap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

VALID_METRICS = frozenset({"sessions", "executions", "commits", "cost_usd", "tokens", "failed"})


def _utc_today() -> date:
    """Today as a UTC calendar day, whatever zone the host is in.

    Every heatmap day is a UTC day (#1371), so the default window has to end on
    one too. ``date.today()`` is the host's local day, and on a host behind UTC
    after 00:00Z it drops the current UTC day from the window (#1907).
    """
    return datetime.now(UTC).date()


@dataclass(frozen=True)
class GetContributionHeatmapQuery:
    """Query to get daily contribution heatmap data.

    Attributes:
        organization_id: Optional org filter.
        system_id: Optional system filter.
        repo_id: Optional repo filter.
        start_date: Start of the date range (default: 365 UTC days ago).
        end_date: End of the date range (default: today, as a UTC day).
        metric: Primary metric for intensity values.
        query_id: Unique identifier for this query.
    """

    organization_id: str | None = None
    system_id: str | None = None
    repo_id: str | None = None
    start_date: date = field(default_factory=lambda: _utc_today() - timedelta(days=365))
    end_date: date = field(default_factory=_utc_today)
    metric: str = "sessions"
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if self.metric not in VALID_METRICS:
            raise ValueError(
                f"Invalid metric '{self.metric}'. Must be one of: {', '.join(sorted(VALID_METRICS))}"
            )
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
