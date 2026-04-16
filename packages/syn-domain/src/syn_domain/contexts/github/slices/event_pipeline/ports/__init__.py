"""Adapter ports for GitHub external API integration.

These Protocols define the contracts that ``syn-adapters/github/`` implements.
Domain services depend only on these ports, never on adapter classes. The
``test_hexagonal_purity`` fitness function enforces this at CI time.
"""

from syn_domain.contexts.github.slices.event_pipeline.ports.checks_api_port import (
    ChecksAPIResult,
    GitHubChecksAPIPort,
)
from syn_domain.contexts.github.slices.event_pipeline.ports.events_api_port import (
    EventsAPIResult,
    GitHubEventsAPIPort,
)

__all__ = [
    "ChecksAPIResult",
    "EventsAPIResult",
    "GitHubChecksAPIPort",
    "GitHubEventsAPIPort",
]
