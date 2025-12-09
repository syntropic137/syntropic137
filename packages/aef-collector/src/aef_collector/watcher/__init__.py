"""File watchers for hook events and Claude transcripts.

This module provides:
- BaseWatcher: Abstract base class for file watchers
- HookWatcher: Watches .agentic/analytics/events.jsonl
- TranscriptWatcher: Watches ~/.claude/projects/**/*.jsonl
- CombinedWatcher: Monitors both sources simultaneously
"""

from aef_collector.watcher.base import BaseWatcher
from aef_collector.watcher.hooks import HookWatcher
from aef_collector.watcher.transcript import TranscriptWatcher

__all__ = [
    "BaseWatcher",
    "HookWatcher",
    "TranscriptWatcher",
]
