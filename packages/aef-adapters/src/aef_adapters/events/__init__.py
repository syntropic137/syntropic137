"""Event bridge for connecting hook events to AEF domain events.

This module bridges the gap between:
- Hook events (from agentic_hooks) written to JSONL files
- AEF domain events (for the event store)

The bridge can operate in two modes:
1. Batch: Read existing JSONL files and translate events
2. Watch: Monitor JSONL files for new events in real-time

Example:
    from aef_adapters.events import EventBridge, JSONLWatcher

    # Batch processing
    bridge = EventBridge(event_store)
    await bridge.process_file(Path(".agentic/analytics/events.jsonl"))

    # Real-time watching
    watcher = JSONLWatcher(Path(".agentic/analytics/events.jsonl"))
    async for event in watcher.watch():
        domain_event = translator.translate(event)
        await event_store.append(domain_event)
"""

from aef_adapters.events.bridge import EventBridge
from aef_adapters.events.translator import (
    DomainEvent,
    HookToDomainTranslator,
)
from aef_adapters.events.watcher import JSONLWatcher

__all__ = [
    "DomainEvent",
    "EventBridge",
    "HookToDomainTranslator",
    "JSONLWatcher",
]
