"""Shared utilities for Agentic Engineering Framework."""

__version__ = "0.1.0"

# Re-export commonly used items for convenience
from aef_shared.logging import LogConfig, configure_logging, get_logger
from aef_shared.settings import AppEnvironment, Settings, get_settings

__all__ = [
    "AppEnvironment",
    "LogConfig",
    "Settings",
    "configure_logging",
    "get_logger",
    "get_settings",
]
