"""Register Claude Plugin slice (issue #726).

Heavy-lifting command slice: fetcher -> sha -> storage upload -> aggregate
register. Used directly by ``syn claude-plugin global add`` and indirectly by
``ensure_registered`` during workflow installation.
"""

from __future__ import annotations

from .projection import ClaudePluginLockProjection, LockEntry
from .RegisterClaudePluginHandler import (
    RegisterClaudePluginHandler,
    RegisterClaudePluginResult,
)

__all__ = [
    "ClaudePluginLockProjection",
    "LockEntry",
    "RegisterClaudePluginHandler",
    "RegisterClaudePluginResult",
]
