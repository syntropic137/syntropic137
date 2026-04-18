"""Public port surface for the GitHub bounded context.

These Protocols are the contracts that ``packages/syn-adapters/github/``
implements. Per ADR-040 + ADR-062, foreign packages MUST import ports
from this public path -- never reach into ``slices/`` or ``services/``.

The ``test_hexagonal_purity`` and ``test_cross_context_public_api``
fitness functions enforce both directions of the boundary at CI time.
"""

from syn_domain.contexts.github.ports.checks_api_port import (
    ChecksAPIResult,
    GitHubChecksAPIPort,
)
from syn_domain.contexts.github.ports.events_api_port import (
    EventsAPIResult,
    GitHubEventsAPIPort,
)

__all__ = [
    "ChecksAPIResult",
    "EventsAPIResult",
    "GitHubChecksAPIPort",
    "GitHubEventsAPIPort",
]
