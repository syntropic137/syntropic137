"""Shared utilities for Agentic Engineering Framework."""

__version__ = "0.1.0"

# Re-export commonly used items for convenience
from aef_shared.logging import LogConfig, configure_logging, get_logger
from aef_shared.settings import AppEnvironment, Settings, get_settings
from aef_shared.workspace_paths import (
    WORKSPACE_ANALYTICS_DIR,
    WORKSPACE_ANALYTICS_FILE,
    WORKSPACE_CLAUDE_DIR,
    WORKSPACE_CONTEXT_DIR,
    WORKSPACE_HOOKS_DIR,
    WORKSPACE_LOGS_DIR,
    WORKSPACE_OUTPUT_DIR,
    WORKSPACE_ROOT,
    WORKSPACE_SETTINGS_FILE,
    WORKSPACE_TASK_FILE,
)

__all__ = [
    "WORKSPACE_ANALYTICS_DIR",
    "WORKSPACE_ANALYTICS_FILE",
    "WORKSPACE_CLAUDE_DIR",
    "WORKSPACE_CONTEXT_DIR",
    "WORKSPACE_HOOKS_DIR",
    "WORKSPACE_LOGS_DIR",
    "WORKSPACE_OUTPUT_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_SETTINGS_FILE",
    "WORKSPACE_TASK_FILE",
    "AppEnvironment",
    "LogConfig",
    "Settings",
    "configure_logging",
    "get_logger",
    "get_settings",
]
