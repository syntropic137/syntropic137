"""ClaudePluginRegistration aggregate (issue #726).

One stream per (source_url, version). Stream id is sha256-derived so concurrent
registers of the same plugin reference collide via ExpectedVersion.NoStream.
"""

from __future__ import annotations

from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
    ClaudePluginRegistrationAggregate,
    compute_claude_plugin_stream_id,
)

__all__ = [
    "ClaudePluginRegistrationAggregate",
    "compute_claude_plugin_stream_id",
]
