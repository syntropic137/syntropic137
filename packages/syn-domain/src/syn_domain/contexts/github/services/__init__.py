"""GitHub bounded context application services.

These services own ingestion orchestration (polling loops, cold-start safety,
HWM filtering) that previously lived in ``apps/syn-api/services/``. Per the
hexagonal architecture (ADR-060 Section 10), they depend only on domain
ports, never on ``syn_adapters`` directly.

Public API:

- ``GitHubEventsCursor`` -- typed cursor with required ``last_event_id`` HWM.
- ``WebhookHealthTracker`` -- webhook freshness tracker for poller mode switching.
- ``GitHubRepoIngestionService`` -- per-repo HistoricalPoller with HWM filter (#694 fix).
- ``GitHubEventIngestionScheduler`` -- outer scheduler with adaptive intervals.
"""

from syn_domain.contexts.github.services.event_ingestion import (
    GitHubEventIngestionScheduler,
    GitHubRepoIngestionService,
)
from syn_domain.contexts.github.services.github_events_cursor import GitHubEventsCursor
from syn_domain.contexts.github.services.webhook_health import WebhookHealthTracker

__all__ = [
    "GitHubEventIngestionScheduler",
    "GitHubEventsCursor",
    "GitHubRepoIngestionService",
    "WebhookHealthTracker",
]
