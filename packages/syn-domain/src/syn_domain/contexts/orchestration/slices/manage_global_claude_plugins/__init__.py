"""Manage Global Claude Plugins slice (issue #726)."""

from __future__ import annotations

from .AddGlobalClaudePluginHandler import (
    AddGlobalClaudePluginHandler,
    AddGlobalClaudePluginResult,
)
from .ListGlobalClaudePluginsHandler import ListGlobalClaudePluginsHandler
from .projection import GlobalClaudePluginEntry, GlobalClaudePluginsProjection
from .RemoveGlobalClaudePluginHandler import (
    GlobalClaudePluginNotFoundError,
    RemoveGlobalClaudePluginHandler,
    RemoveGlobalClaudePluginResult,
)

__all__ = [
    "AddGlobalClaudePluginHandler",
    "AddGlobalClaudePluginResult",
    "GlobalClaudePluginEntry",
    "GlobalClaudePluginNotFoundError",
    "GlobalClaudePluginsProjection",
    "ListGlobalClaudePluginsHandler",
    "RemoveGlobalClaudePluginHandler",
    "RemoveGlobalClaudePluginResult",
]
