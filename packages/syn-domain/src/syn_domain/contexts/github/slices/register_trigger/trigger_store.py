"""Trigger query store — re-exports from _shared.

Canonical location: syn_domain.contexts.github._shared.trigger_query_store
This module re-exports for backward compatibility.
"""

from syn_domain.contexts.github._shared.trigger_query_store import (
    IndexedTrigger,
    InMemoryTriggerQueryStore,
    InMemoryTriggerStore,
    TriggerQueryStore,
    TriggerStore,
    get_trigger_query_store,
    get_trigger_store,
    reset_trigger_store,
    set_trigger_store,
)

__all__ = [
    "InMemoryTriggerQueryStore",
    "InMemoryTriggerStore",
    "IndexedTrigger",
    "TriggerQueryStore",
    "TriggerStore",
    "get_trigger_query_store",
    "get_trigger_store",
    "reset_trigger_store",
    "set_trigger_store",
]
