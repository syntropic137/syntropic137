"""Centralized settings management using Pydantic.

This module provides type-safe, validated environment configuration.
All settings are validated on application startup - failing fast if
required values are missing or invalid.

Usage:
    from syn_shared.settings import get_settings

    settings = get_settings()
    print(settings.syn_observability_db_url)

    # Git identity for workspace commits
    git = settings.git_identity
    print(f"Commits as: {git.user_name} <{git.user_email}>")

    # GitHub App settings
    github = settings.github
    if github.is_configured:
        print(f"GitHub App: {github.app_name}")

    # Container logging settings
    logging = settings.container_logging
    print(f"Log level: {logging.level}")

    # Object storage settings
    storage = settings.storage
    print(f"Storage provider: {storage.provider}")

Environment Variables:
    See Settings class for full list with descriptions.
    Required vars will cause immediate failure if missing.

    SYN_GIT_* - Git identity and credentials
    SYN_GITHUB_* - GitHub App configuration
    SYN_LOGGING_* - Container logging configuration
    SYN_STORAGE_* - Object storage configuration
"""

from syn_shared.settings.config import (
    AppEnvironment,
    Settings,
    get_settings,
    reset_settings,
)
from syn_shared.settings.github import (
    GitHubAppSettings,
    get_github_settings,
    reset_github_settings,
)
from syn_shared.settings.infra import InfraSettings
from syn_shared.settings.storage import (
    StorageProvider,
    StorageSettings,
)
from syn_shared.settings.workspace import (
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
    "GitHubAppSettings",
    "GitIdentityResolver",
    "GitIdentitySettings",
    "InfraSettings",
    "IsolationBackend",
    "Settings",
    "StorageProvider",
    "StorageSettings",
    "WorkspaceSecuritySettings",
    "WorkspaceSettings",
    "get_default_isolation_backend",
    "get_github_settings",
    "get_settings",
    "reset_github_settings",
    "reset_settings",
]
