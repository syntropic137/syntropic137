"""GlobalClaudePluginRegistry aggregate (issue #726).

Singleton aggregate: one stream id `global-claude-plugins` holding the mutable
list of globally-active claude plugins. Add/remove are name-keyed; the lock
projection (Phase 5) carries the (source_url, version) -> resolved_sha mapping.
"""

from __future__ import annotations

from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
    GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
    GlobalClaudePluginEntry,
    GlobalClaudePluginRegistryAggregate,
)

__all__ = [
    "GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID",
    "GlobalClaudePluginEntry",
    "GlobalClaudePluginRegistryAggregate",
]
