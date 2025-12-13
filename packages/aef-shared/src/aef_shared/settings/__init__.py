"""Centralized settings management using Pydantic.

This module provides type-safe, validated environment configuration.
All settings are validated on application startup - failing fast if
required values are missing or invalid.

Usage:
    from aef_shared.settings import get_settings

    settings = get_settings()
    print(settings.database_url)

    # Git identity for workspace commits
    git = settings.git_identity
    print(f"Commits as: {git.user_name} <{git.user_email}>")

    # Container logging settings
    logging = settings.container_logging
    print(f"Log level: {logging.level}")

    # Object storage settings
    storage = settings.storage
    print(f"Storage provider: {storage.provider}")

Environment Variables:
    See Settings class for full list with descriptions.
    Required vars will cause immediate failure if missing.

    AEF_GIT_* - Git identity and credentials
    AEF_LOGGING_* - Container logging configuration
    AEF_STORAGE_* - Object storage configuration
"""

from aef_shared.settings.config import (
    AppEnvironment,
    Settings,
    get_settings,
    reset_settings,
)
from aef_shared.settings.storage import (
    StorageProvider,
    StorageSettings,
)
from aef_shared.settings.workspace import (
    CloudProvider,
    ContainerLoggingSettings,
    GitCredentialType,
    GitIdentityResolver,
    GitIdentitySettings,
    IsolationBackend,
    WorkspaceSecuritySettings,
    WorkspaceSettings,
    get_default_isolation_backend,
)

__all__ = [
    "AppEnvironment",
    "CloudProvider",
    "ContainerLoggingSettings",
    "GitCredentialType",
    "GitIdentityResolver",
    "GitIdentitySettings",
    "IsolationBackend",
    "Settings",
    "StorageProvider",
    "StorageSettings",
    "WorkspaceSecuritySettings",
    "WorkspaceSettings",
    "get_default_isolation_backend",
    "get_settings",
    "reset_settings",
]
