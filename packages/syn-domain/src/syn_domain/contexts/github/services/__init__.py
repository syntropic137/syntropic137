"""GitHub bounded context application services.

These services own ingestion orchestration (polling loops, cold-start safety,
HWM filtering) that previously lived in ``apps/syn-api/services/``. Per the
hexagonal architecture (ADR-060 Section 10), they depend only on domain
ports, never on ``syn_adapters`` directly.

Public API:

- ``GitHubEventsCursor`` -- typed cursor with required ``last_event_id`` HWM.
"""

from syn_domain.contexts.github.services.github_events_cursor import GitHubEventsCursor

__all__ = [
    "GitHubEventsCursor",
]
