"""Centralized settings management using Pydantic.

This module provides type-safe, validated environment configuration.
All settings are validated on application startup - failing fast if
required values are missing or invalid.

Usage:
    from aef_shared.settings import get_settings

    settings = get_settings()
    print(settings.database_url)

Environment Variables:
    See Settings class for full list with descriptions.
    Required vars will cause immediate failure if missing.
"""

from aef_shared.settings.config import (
    AppEnvironment,
    Settings,
    get_settings,
    reset_settings,
)

__all__ = [
    "AppEnvironment",
    "Settings",
    "get_settings",
    "reset_settings",
]
