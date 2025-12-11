"""Query for workspace metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GetWorkspaceMetricsQuery:
    """Query to get workspace performance metrics.

    Can filter by:
    - Session ID
    - Isolation backend
    - Time range
    """

    session_id: str | None = None
    isolation_backend: str | None = None
    workflow_id: str | None = None
    limit: int = 100
